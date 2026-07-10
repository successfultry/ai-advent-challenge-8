from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from shared.client import available_providers, get_client, timed_response
from shared.config import PROVIDERS
from week_06.local_client import OllamaClient, OllamaClientError

DEFAULT_DB = Path("data/week_05/rag_index.sqlite")
DEFAULT_DATASET = Path("week_05/eval/questions.json")
DEFAULT_EVAL_OUTPUT = Path("week_06/eval/day28_results.json")
DEFAULT_DAY29_OUTPUT = Path("week_06/eval/day29_optimization_results.json")
DEFAULT_TOP_K = 5
DEFAULT_MAX_CHARS_PER_CHUNK = 900
DEFAULT_MAX_TOTAL_CONTEXT_CHARS = 7000
INSUFFICIENT_CONTEXT = "The provided context is insufficient."
# Retrieval is held constant (top_k=5) so baseline vs optimized isolates the
# generation change (prompt + sampling params), not the retrieved context.
BASELINE_TOP_K = 5
OPTIMIZED_TOP_K = 5
OPTIMIZED_TEMPERATURE = 0.2
OPTIMIZED_TOP_P = 0.9
OPTIMIZED_MAX_TOKENS = 160
OPTIMIZE_REPEATS_DEFAULT = 1
WARMUP_MAX_TOKENS = 8
QUANT_COMPARISON_MODEL = "qwen2.5-coder:7b-instruct-q3_K_M"

BASELINE_PROMPT = (
    "You are a strict RAG assistant.\n"
    "Answer using ONLY the provided context.\n"
    f"If context is insufficient, reply exactly: '{INSUFFICIENT_CONTEXT}'.\n"
    "End your answer with a line in this format: Sources: [C1], [C3]\n\n"
    "Question: {question}\n\n"
    "Context:\n{context}"
)

OPTIMIZED_PROMPT = (
    "You are a strict RAG assistant for technical course notes.\n"
    "Rules:\n"
    "1) Answer in Russian, in 3-5 concise sentences. Keep standard technical terms in English.\n"
    "2) Use ONLY the provided context. If it is insufficient, answer exactly: "
    f"'{INSUFFICIENT_CONTEXT}'\n"
    "3) The LAST line of your answer MUST be exactly: Sources: [C1], [C3] "
    "(list every chunk label you actually used, or Sources: [] if none).\n\n"
    "Question: {question}\n\n"
    "Context:\n{context}"
)


@dataclass(frozen=True)
class IndexRun:
    id: str
    strategy: str
    embedding_model: str
    created_at: str
    source_root: str


@dataclass(frozen=True)
class ChunkRow:
    chunk_id: str
    source: str
    title: str
    section: str
    text: str
    start_char: int


@dataclass(frozen=True)
class RetrievedChunk:
    label: str
    chunk_id: str
    source: str
    title: str
    section: str
    text: str
    score: float


@dataclass(frozen=True)
class GeneratedAnswer:
    provider: str
    model: str
    text: str
    latency_s: float
    finish_reason: str
    used_labels: list[str]
    fallback_reason: str | None = None
    tokens_out: int | None = None
    prompt_tokens: int | None = None
    tokens_per_sec: float | None = None
    load_seconds: float | None = None


@dataclass(frozen=True)
class RagTurn:
    run: IndexRun
    retrieval_latency_s: float
    generation_latency_s: float
    retrieved: list[RetrievedChunk]
    answer: GeneratedAnswer


@dataclass(frozen=True)
class GenerationSettings:
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    context_window: int | None = None


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"\w+", _normalize_text(text), flags=re.UNICODE) if token]


def _display_path(value: str | Path) -> str:
    path = Path(value)
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(value)


def _extract_used_labels(answer: str, max_label: int) -> list[str]:
    seen: list[str] = []
    for match in re.finditer(r"C(\d+)", answer):
        idx = int(match.group(1))
        if 1 <= idx <= max_label:
            label = f"C{idx}"
            if label not in seen:
                seen.append(label)
    return seen


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _pick_run(db_path: Path, strategy: str | None) -> IndexRun:
    if not db_path.exists():
        raise FileNotFoundError(
            f"Index DB not found: {_display_path(db_path)}. "
            "Build Week 5 index first: uv run python -m week_05.main compare "
            '--source "week_05/corpus"'
        )
    with _connect(db_path) as conn:
        if strategy is not None:
            row = conn.execute(
                """
                SELECT id, strategy, embedding_model, created_at, source_root
                FROM index_runs
                WHERE strategy = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (strategy,),
            ).fetchone()
            if row is None:
                raise ValueError(
                    f"No run found for strategy={strategy} in {_display_path(db_path)}. "
                    "Run Week 5 indexing first."
                )
        else:
            row = conn.execute(
                """
                SELECT id, strategy, embedding_model, created_at, source_root
                FROM index_runs
                WHERE strategy = 'structure'
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                row = conn.execute(
                    """
                    SELECT id, strategy, embedding_model, created_at, source_root
                    FROM index_runs
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
    if row is None:
        raise ValueError(
            f"No usable index run found in {_display_path(db_path)}. "
            "Build Week 5 index first: uv run python -m week_05.main compare "
            '--source "week_05/corpus"'
        )
    return IndexRun(
        id=str(row["id"]),
        strategy=str(row["strategy"]),
        embedding_model=str(row["embedding_model"]),
        created_at=str(row["created_at"]),
        source_root=str(row["source_root"]),
    )


def _load_chunks(db_path: Path, run_id: str) -> list[ChunkRow]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT chunk_id, source, title, section, text, start_char
            FROM chunks
            WHERE run_id = ?
            ORDER BY source, start_char
            """,
            (run_id,),
        ).fetchall()
    return [
        ChunkRow(
            chunk_id=str(row["chunk_id"]),
            source=str(row["source"]),
            title=str(row["title"]),
            section=str(row["section"]),
            text=str(row["text"]),
            start_char=int(row["start_char"]),
        )
        for row in rows
    ]


def _lexical_retrieve(question: str, chunks: list[ChunkRow], top_k: int) -> list[RetrievedChunk]:
    query_tokens = _tokenize(question)
    if not query_tokens or top_k <= 0:
        return []
    query_tf = Counter(query_tokens)
    terms = list(query_tf.keys())

    indexed: list[tuple[ChunkRow, Counter[str]]] = []
    doc_freq: Counter[str] = Counter()
    for chunk in chunks:
        chunk_tf = Counter(_tokenize(chunk.text))
        indexed.append((chunk, chunk_tf))
        for term in terms:
            if chunk_tf.get(term, 0) > 0:
                doc_freq[term] += 1

    total_docs = max(1, len(chunks))
    idf = {term: math.log((total_docs + 1) / (doc_freq.get(term, 0) + 1)) + 1.0 for term in terms}

    scored: list[tuple[float, ChunkRow]] = []
    for chunk, chunk_tf in indexed:
        score = 0.0
        for term, qtf in query_tf.items():
            ctf = chunk_tf.get(term, 0)
            if ctf <= 0:
                continue
            score += float(ctf) * idf[term] * float(qtf)
        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda item: (-item[0], item[1].source, item[1].start_char, item[1].chunk_id))
    selected = scored[:top_k]
    return [
        RetrievedChunk(
            label=f"C{idx}",
            chunk_id=chunk.chunk_id,
            source=chunk.source,
            title=chunk.title,
            section=chunk.section,
            text=chunk.text,
            score=score,
        )
        for idx, (score, chunk) in enumerate(selected, start=1)
    ]


def _build_context(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return ""
    parts: list[str] = []
    used_total = 0
    for chunk in chunks:
        text = chunk.text.strip()
        if len(text) > DEFAULT_MAX_CHARS_PER_CHUNK:
            text = text[:DEFAULT_MAX_CHARS_PER_CHUNK].rstrip() + "..."
        if used_total + len(text) > DEFAULT_MAX_TOTAL_CONTEXT_CHARS and parts:
            break
        used_total += len(text)
        parts.append(
            f"[{chunk.label}] source={chunk.source} section={chunk.section} "
            f"chunk_id={chunk.chunk_id} "
            f"score={chunk.score:.4f}\n{text}"
        )
    return "\n\n".join(parts)


def _build_prompt(
    question: str,
    chunks: list[RetrievedChunk],
    *,
    prompt_template: str = OPTIMIZED_PROMPT,
) -> str:
    context = _build_context(chunks)
    return prompt_template.format(
        question=question.strip(),
        context=context if context else "(empty)",
    )


def _generate_local(
    provider_name: str,
    prompt: str,
    labels_count: int,
    *,
    settings: GenerationSettings | None = None,
    model_override: str | None = None,
) -> GeneratedAnswer:
    client = OllamaClient(provider_name=provider_name, model_override=model_override)
    response = client.generate(
        prompt,
        temperature=settings.temperature if settings else None,
        top_p=settings.top_p if settings else None,
        max_tokens=settings.max_tokens if settings else None,
        context_window=settings.context_window if settings else None,
    )
    used = _extract_used_labels(response.text, labels_count)
    return GeneratedAnswer(
        provider=provider_name,
        model=client.model_id,
        text=response.text,
        latency_s=response.latency_seconds,
        finish_reason=response.finish_reason,
        used_labels=used,
        fallback_reason=None,
        tokens_out=response.tokens_out,
        prompt_tokens=response.prompt_tokens,
        tokens_per_sec=response.tokens_per_sec,
        load_seconds=response.load_seconds,
    )


def _generate_cloud(provider_name: str, prompt: str, labels_count: int) -> GeneratedAnswer:
    client, model_id = get_client(provider_name)
    messages = [{"role": "user", "content": prompt}]
    text, finish_reason, _usage, latency = timed_response(client, model_id, messages)
    used = _extract_used_labels(text, labels_count)
    return GeneratedAnswer(
        provider=provider_name,
        model=model_id,
        text=text,
        latency_s=latency,
        finish_reason=finish_reason,
        used_labels=used,
        fallback_reason=None,
    )


def _fallback_answer(provider_name: str, reason: str) -> GeneratedAnswer:
    return GeneratedAnswer(
        provider=provider_name,
        model="n/a",
        text=INSUFFICIENT_CONTEXT,
        latency_s=0.0,
        finish_reason="fallback",
        used_labels=[],
        fallback_reason=reason,
    )


def run_local_rag(
    *,
    db_path: Path,
    question: str,
    top_k: int,
    strategy: str | None,
    provider_name: str,
    prompt_template: str = OPTIMIZED_PROMPT,
    generation_settings: GenerationSettings | None = None,
    model_override: str | None = None,
) -> RagTurn:
    run = _pick_run(db_path, strategy)
    chunks = _load_chunks(db_path, run.id)

    t0 = time.perf_counter()
    retrieved = _lexical_retrieve(question, chunks, top_k=top_k)
    retrieval_latency = time.perf_counter() - t0

    if not retrieved:
        answer = _fallback_answer(provider_name, "no_lexical_hits")
        generation_latency = 0.0
    else:
        prompt = _build_prompt(question, retrieved, prompt_template=prompt_template)
        try:
            answer = _generate_local(
                provider_name,
                prompt,
                len(retrieved),
                settings=generation_settings,
                model_override=model_override,
            )
        except OllamaClientError as exc:
            raise RuntimeError(str(exc)) from exc
        generation_latency = answer.latency_s

    return RagTurn(
        run=run,
        retrieval_latency_s=retrieval_latency,
        generation_latency_s=generation_latency,
        retrieved=retrieved,
        answer=answer,
    )


def _l2_norm(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    denom = _l2_norm(a) * _l2_norm(b)
    if denom <= 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=False)) / denom


def _load_embedded_chunks(db_path: Path, run_id: str) -> list[tuple[ChunkRow, list[float]]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT chunk_id, source, title, section, text, start_char, embedding_json
            FROM chunks
            WHERE run_id = ?
            ORDER BY source, start_char
            """,
            (run_id,),
        ).fetchall()
    embedded: list[tuple[ChunkRow, list[float]]] = []
    for row in rows:
        raw = row["embedding_json"]
        if raw is None:
            continue
        vector = [float(value) for value in json.loads(str(raw))]
        chunk = ChunkRow(
            chunk_id=str(row["chunk_id"]),
            source=str(row["source"]),
            title=str(row["title"]),
            section=str(row["section"]),
            text=str(row["text"]),
            start_char=int(row["start_char"]),
        )
        embedded.append((chunk, vector))
    return embedded


def _vector_retrieve(
    query_vector: list[float],
    embedded: list[tuple[ChunkRow, list[float]]],
    top_k: int,
) -> list[RetrievedChunk]:
    if not query_vector or top_k <= 0:
        return []
    query_dim = len(query_vector)
    scored: list[tuple[float, ChunkRow]] = []
    for chunk, vector in embedded:
        if len(vector) != query_dim:
            continue
        score = _cosine_similarity(query_vector, vector)
        scored.append((score, chunk))
    scored.sort(key=lambda item: (-item[0], item[1].source, item[1].start_char, item[1].chunk_id))
    selected = scored[:top_k]
    return [
        RetrievedChunk(
            label=f"C{idx}",
            chunk_id=chunk.chunk_id,
            source=chunk.source,
            title=chunk.title,
            section=chunk.section,
            text=chunk.text,
            score=score,
        )
        for idx, (score, chunk) in enumerate(selected, start=1)
    ]


def _openai_provider_name() -> str | None:
    for name, provider in PROVIDERS.items():
        if provider.api_key_env == "OPENAI_API_KEY":
            return name
    return None


def _cloud_retrieval_status(run: IndexRun) -> tuple[bool, str]:
    if not run.embedding_model.startswith("text-embedding"):
        return (
            False,
            f"indexed vectors are '{run.embedding_model}', not OpenAI; "
            "cloud vector retrieval needs the same embedding space",
        )
    name = _openai_provider_name()
    if name is None or name not in available_providers():
        return (
            False,
            "OPENAI_API_KEY missing (needed to embed the query into the indexed vector space)",
        )
    return True, ""


def _embed_query_openai(model: str, text: str) -> list[float]:
    name = _openai_provider_name()
    if name is None:
        raise RuntimeError("No OpenAI provider configured for query embedding")
    client, _model_id = get_client(name)
    response = client.embeddings.create(model=model, input=[text])
    return [float(value) for value in response.data[0].embedding]


def run_cloud_rag(
    *,
    db_path: Path,
    question: str,
    top_k: int,
    strategy: str | None,
    cloud_provider: str,
) -> RagTurn:
    run = _pick_run(db_path, strategy)
    embedded = _load_embedded_chunks(db_path, run.id)

    t0 = time.perf_counter()
    query_vector = _embed_query_openai(run.embedding_model, question)
    retrieved = _vector_retrieve(query_vector, embedded, top_k=top_k)
    retrieval_latency = time.perf_counter() - t0

    if not retrieved:
        answer = _fallback_answer(cloud_provider, "no_vector_hits")
        generation_latency = 0.0
    else:
        prompt = _build_prompt(question, retrieved)
        answer = _generate_cloud(cloud_provider, prompt, len(retrieved))
        generation_latency = answer.latency_s

    return RagTurn(
        run=run,
        retrieval_latency_s=retrieval_latency,
        generation_latency_s=generation_latency,
        retrieved=retrieved,
        answer=answer,
    )


def _cloud_status(
    run: IndexRun, cloud_provider: str | None, cloud_retrieval: str
) -> tuple[bool, str]:
    if cloud_provider is None:
        return False, "no cloud API key for generation"
    if cloud_retrieval == "vector":
        return _cloud_retrieval_status(run)
    return True, ""


def _cloud_turn_from_local(question: str, cloud_provider: str, local_turn: RagTurn) -> RagTurn:
    retrieved = local_turn.retrieved
    if not retrieved:
        answer = _fallback_answer(cloud_provider, "no_lexical_hits")
        generation_latency = 0.0
    else:
        prompt = _build_prompt(question, retrieved)
        answer = _generate_cloud(cloud_provider, prompt, len(retrieved))
        generation_latency = answer.latency_s
    return RagTurn(
        run=local_turn.run,
        retrieval_latency_s=local_turn.retrieval_latency_s,
        generation_latency_s=generation_latency,
        retrieved=retrieved,
        answer=answer,
    )


def _build_cloud_turn(
    *,
    db_path: Path,
    question: str,
    top_k: int,
    strategy: str | None,
    cloud_provider: str,
    cloud_retrieval: str,
    local_turn: RagTurn,
) -> tuple[RagTurn, str]:
    if cloud_retrieval == "vector":
        turn = run_cloud_rag(
            db_path=db_path,
            question=question,
            top_k=top_k,
            strategy=strategy,
            cloud_provider=cloud_provider,
        )
        return turn, f"vector ({turn.run.embedding_model}, cloud embeddings)"
    turn = _cloud_turn_from_local(question, cloud_provider, local_turn)
    return turn, "lexical (shared local context)"


def _cloud_candidates() -> list[str]:
    names = set(available_providers())
    return [
        name
        for name, provider in PROVIDERS.items()
        if provider.api_key_env is not None and name in names
    ]


def _pick_cloud_provider(preferred: str | None) -> str | None:
    candidates = _cloud_candidates()
    if not candidates:
        return None
    if preferred:
        return preferred if preferred in candidates else None
    return candidates[0]


def _print_chunks(chunks: list[RetrievedChunk]) -> None:
    print("retrieved:")
    if not chunks:
        print("  - none (no lexical hits)")
        return
    for chunk in chunks:
        print(
            f"  - [{chunk.label}] source={_display_path(chunk.source)} "
            f"section={chunk.section} chunk_id={chunk.chunk_id} score={chunk.score:.4f}"
        )


def _print_answer(title: str, turn: RagTurn, retrieval_label: str) -> None:
    answer = turn.answer
    total = turn.retrieval_latency_s + turn.generation_latency_s
    print(
        f"\n[{title}] retrieval={retrieval_label} generation={answer.provider} model={answer.model}"
    )
    print(
        f"retrieval_latency_s={turn.retrieval_latency_s:.2f} "
        f"generation_latency_s={turn.generation_latency_s:.2f} "
        f"total_latency_s={total:.2f} "
        f"finish_reason={answer.finish_reason}"
    )
    if answer.tokens_per_sec is not None:
        print(
            f"tokens_out={answer.tokens_out} tokens_per_sec={answer.tokens_per_sec:.1f} "
            f"load_seconds={answer.load_seconds or 0.0:.2f}"
        )
    if answer.fallback_reason:
        print(f"fallback_reason={answer.fallback_reason}")
    if answer.used_labels:
        print(f"used_sources={', '.join(answer.used_labels)}")
    print("\nanswer:")
    print(answer.text)


def _normalize_bool_hit(expected: list[str], text: str) -> float:
    if not expected:
        return 1.0
    lowered = _normalize_text(text)
    hits = sum(1 for token in expected if _normalize_text(token) in lowered)
    return hits / len(expected)


def _source_hit(expected_sources: list[str], chunks: list[RetrievedChunk]) -> bool:
    if not expected_sources:
        return False
    names = {Path(chunk.source).name for chunk in chunks}
    return any(Path(item).name in names for item in expected_sources)


def _sources_format_ok(answer_text: str) -> bool:
    lines = [line.strip() for line in answer_text.splitlines() if line.strip()]
    if not lines:
        return False
    # accept both "[C1], [C3]" and "[C1, C3]" styles emitted by the model
    normalized = lines[-1].replace("], [", ", ").replace("],[", ", ")
    return bool(re.fullmatch(r"Sources:\s*\[(?:C\d+(?:,\s*C\d+)*)?\]", normalized))


def _read_questions(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Questions dataset must be a JSON array")
    return payload


def _turn_block(
    turn: RagTurn,
    expected: list[str],
    expected_sources: list[str],
    retrieval_label: str,
) -> dict:
    used = set(turn.answer.used_labels)
    used_sources = [
        {
            "label": chunk.label,
            "source": _display_path(chunk.source),
            "section": chunk.section,
            "chunk_id": chunk.chunk_id,
        }
        for chunk in turn.retrieved
        if chunk.label in used
    ]
    return {
        "retrieval": retrieval_label,
        "generation_provider": turn.answer.provider,
        "model": turn.answer.model,
        "finish_reason": turn.answer.finish_reason,
        "retrieved_count": len(turn.retrieved),
        "keyword_recall": _normalize_bool_hit(expected, turn.answer.text),
        "source_hit": _source_hit(expected_sources, turn.retrieved),
        "retrieval_latency_s": turn.retrieval_latency_s,
        "generation_latency_s": turn.generation_latency_s,
        "total_latency_s": turn.retrieval_latency_s + turn.generation_latency_s,
        "answer_text": turn.answer.text,
        "answer_chars": len(turn.answer.text),
        "sources_format_ok": _sources_format_ok(turn.answer.text),
        "used_source_labels": turn.answer.used_labels,
        "used_sources": used_sources,
        "fallback_reason": turn.answer.fallback_reason,
        "tokens_out": turn.answer.tokens_out,
        "tokens_per_sec": turn.answer.tokens_per_sec,
        "load_seconds": turn.answer.load_seconds,
    }


def _avg(blocks: list[dict], key: str) -> float:
    if not blocks:
        return 0.0
    return sum(block.get(key, 0.0) for block in blocks) / len(blocks)


def _avg_skip_none(blocks: list[dict], key: str) -> float | None:
    values = [block[key] for block in blocks if block.get(key) is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _aggregate_blocks(blocks: list[dict]) -> dict:
    return {
        "count": len(blocks),
        "avg_keyword_recall": _avg(blocks, "keyword_recall"),
        "source_hit_rate": (
            sum(1 for block in blocks if block.get("source_hit")) / len(blocks) if blocks else 0.0
        ),
        "avg_retrieved_count": _avg(blocks, "retrieved_count"),
        "avg_retrieval_latency_s": _avg(blocks, "retrieval_latency_s"),
        "avg_generation_latency_s": _avg(blocks, "generation_latency_s"),
        "avg_total_latency_s": _avg(blocks, "total_latency_s"),
        "avg_answer_chars": _avg(blocks, "answer_chars"),
        "avg_tokens_per_sec": _avg_skip_none(blocks, "tokens_per_sec"),
        "avg_load_seconds": _avg_skip_none(blocks, "load_seconds"),
        "sources_format_rate": (
            sum(1 for block in blocks if block.get("sources_format_ok")) / len(blocks)
            if blocks
            else 0.0
        ),
        "fallback_count": sum(1 for block in blocks if block.get("fallback_reason")),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Week 06 Day 28 - local lexical RAG over Week 5 index"
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to Week 5 SQLite index")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ask = sub.add_parser("ask", help="Run local lexical retrieval + local generation")
    p_ask.add_argument(
        "--question",
        default=None,
        help="Question to answer; omit for interactive loop",
    )
    p_ask.add_argument("--strategy", choices=["fixed", "structure"], default=None)
    p_ask.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p_ask.add_argument("--provider", default="Qwen2.5 Coder 7B (Ollama, local)")

    p_compare = sub.add_parser(
        "compare",
        help="Compare local generation vs cloud generation on the same retrieval",
    )
    p_compare.add_argument("--question", required=True)
    p_compare.add_argument("--strategy", choices=["fixed", "structure"], default=None)
    p_compare.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p_compare.add_argument("--provider", default="Qwen2.5 Coder 7B (Ollama, local)")
    p_compare.add_argument("--cloud-provider", default=None)
    p_compare.add_argument(
        "--cloud-retrieval",
        choices=["lexical", "vector"],
        default="lexical",
        help="lexical: cloud reuses the same local lexical context (default, fair 1-variable "
        "comparison); vector: cloud does its own OpenAI vector retrieval over stored vectors",
    )

    p_eval = sub.add_parser(
        "eval",
        help="Evaluate local vs cloud RAG on Week 5 questions (symmetric metrics)",
    )
    p_eval.add_argument("--dataset", default=str(DEFAULT_DATASET))
    p_eval.add_argument("--output", default=str(DEFAULT_EVAL_OUTPUT))
    p_eval.add_argument("--strategy", choices=["fixed", "structure"], default=None)
    p_eval.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p_eval.add_argument("--provider", default="Qwen2.5 Coder 7B (Ollama, local)")
    p_eval.add_argument("--limit", type=int, default=None)
    p_eval.add_argument("--cloud-provider", default=None)
    p_eval.add_argument(
        "--cloud-retrieval",
        choices=["lexical", "vector"],
        default="lexical",
        help="lexical: cloud reuses the same local lexical context (default); "
        "vector: cloud does its own OpenAI vector retrieval",
    )

    p_opt = sub.add_parser(
        "optimize",
        help="Day 29: compare baseline vs optimized local generation settings",
    )
    p_opt.add_argument("--dataset", default=str(DEFAULT_DATASET))
    p_opt.add_argument("--output", default=str(DEFAULT_DAY29_OUTPUT))
    p_opt.add_argument("--strategy", choices=["fixed", "structure"], default=None)
    p_opt.add_argument("--provider", default="Qwen2.5 Coder 7B (Ollama, local)")
    p_opt.add_argument("--limit", type=int, default=None)
    p_opt.add_argument(
        "--question",
        default=None,
        help="One-shot baseline-vs-optimized on a single question (no JSON report)",
    )
    p_opt.add_argument(
        "--interactive",
        action="store_true",
        help="Interactive baseline-vs-optimized loop (no JSON report)",
    )
    p_opt.add_argument(
        "--repeats",
        type=int,
        default=OPTIMIZE_REPEATS_DEFAULT,
        help="Repeats per question per arm; latency/tokens_per_sec use the median "
        "(default 1 = single shot, matches ask/compare speed)",
    )
    p_opt.add_argument(
        "--quant-model",
        default=None,
        help=f"Also run a third arm on this Ollama model tag (e.g. {QUANT_COMPARISON_MODEL}) "
        "using the optimized settings, to compare quantization variants. "
        "Model must already be pulled (`ollama pull <tag>`); skipped otherwise.",
    )
    return parser.parse_args()


def _ensure_console_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _validate_local_provider(name: str) -> str:
    provider = PROVIDERS.get(name)
    if provider is None:
        raise ValueError(f"Unknown provider: {name}")
    if provider.api_key_env is not None:
        raise ValueError(f"Provider is not local: {name}")
    return name


def _run_ask(args: argparse.Namespace) -> int:
    provider = _validate_local_provider(args.provider)
    db_path = Path(args.db)

    def answer_once(question: str) -> None:
        turn = run_local_rag(
            db_path=db_path,
            question=question,
            top_k=args.top_k,
            strategy=args.strategy,
            provider_name=provider,
        )
        print(
            f"run_id={turn.run.id} strategy={turn.run.strategy} "
            f"embedding_model={turn.run.embedding_model}"
        )
        _print_chunks(turn.retrieved)
        _print_answer("local", turn, "lexical (local, no network)")

    if args.question is not None and str(args.question).strip():
        answer_once(str(args.question).strip())
        return 0

    print("Interactive mode. Type a question, empty line or 'exit'/'quit' to stop.")
    while True:
        try:
            question = input("\nquestion> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question or question.lower() in {"exit", "quit"}:
            break
        answer_once(question)
    return 0


def _run_compare(args: argparse.Namespace) -> int:
    provider = _validate_local_provider(args.provider)
    db_path = Path(args.db)
    question = args.question.strip()
    if not question:
        raise ValueError("Question must not be empty")

    local_turn = run_local_rag(
        db_path=db_path,
        question=question,
        top_k=args.top_k,
        strategy=args.strategy,
        provider_name=provider,
    )
    print(
        f"run_id={local_turn.run.id} strategy={local_turn.run.strategy} "
        f"embedding_model={local_turn.run.embedding_model}"
    )
    print("\n== LOCAL pipeline (lexical retrieval + local generation) ==")
    _print_chunks(local_turn.retrieved)
    _print_answer("local", local_turn, "lexical (local, no network)")

    cloud_retrieval = args.cloud_retrieval
    retr_desc = "own vector retrieval" if cloud_retrieval == "vector" else "same lexical context"
    print(f"\n== CLOUD pipeline ({retr_desc} + cloud generation) ==")
    cloud_provider = _pick_cloud_provider(args.cloud_provider)
    ready, reason = _cloud_status(local_turn.run, cloud_provider, cloud_retrieval)
    if not ready:
        print(f"[cloud] skipped: {reason}")
        return 0
    try:
        cloud_turn, cloud_label = _build_cloud_turn(
            db_path=db_path,
            question=question,
            top_k=args.top_k,
            strategy=args.strategy,
            cloud_provider=cloud_provider,
            cloud_retrieval=cloud_retrieval,
            local_turn=local_turn,
        )
    except Exception as exc:
        print(f"[cloud] skipped: {exc}")
        return 0
    if cloud_retrieval == "vector":
        _print_chunks(cloud_turn.retrieved)
    _print_answer("cloud", cloud_turn, cloud_label)
    return 0


def _run_eval(args: argparse.Namespace) -> int:
    provider = _validate_local_provider(args.provider)
    db_path = Path(args.db)
    dataset_path = Path(args.dataset)
    output_path = Path(args.output)

    questions = _read_questions(dataset_path)
    if args.limit is not None and args.limit >= 0:
        questions = questions[: args.limit]

    cloud_retrieval = args.cloud_retrieval
    cloud_provider = _pick_cloud_provider(args.cloud_provider)
    probe_run = _pick_run(db_path, args.strategy)
    cloud_enabled, cloud_reason = _cloud_status(probe_run, cloud_provider, cloud_retrieval)

    results: list[dict] = []
    success_count = 0
    failure_count = 0

    for item in questions:
        qid = str(item.get("id", "unknown"))
        question = str(item.get("question", "")).strip()
        expected = [str(v) for v in item.get("expected", [])]
        expected_sources = [str(v) for v in item.get("expected_sources", [])]
        if not question:
            failure_count += 1
            continue

        try:
            local_turn = run_local_rag(
                db_path=db_path,
                question=question,
                top_k=args.top_k,
                strategy=args.strategy,
                provider_name=provider,
            )
            local_block = _turn_block(local_turn, expected, expected_sources, "lexical (local)")
            success_count += 1

            cloud_block: dict | None = None
            if cloud_enabled:
                try:
                    cloud_turn, cloud_label = _build_cloud_turn(
                        db_path=db_path,
                        question=question,
                        top_k=args.top_k,
                        strategy=args.strategy,
                        cloud_provider=cloud_provider,
                        cloud_retrieval=cloud_retrieval,
                        local_turn=local_turn,
                    )
                    cloud_block = _turn_block(cloud_turn, expected, expected_sources, cloud_label)
                except Exception as exc:
                    cloud_block = {"error": str(exc)}

            results.append(
                {
                    "id": qid,
                    "question": question,
                    "local": local_block,
                    "cloud": cloud_block,
                }
            )
            cloud_kw = (
                f"{cloud_block['keyword_recall']:.2f}"
                if cloud_block and "error" not in cloud_block
                else "-"
            )
            print(
                f"- {qid}: local_kw={local_block['keyword_recall']:.2f} "
                f"cloud_kw={cloud_kw} "
                f"local_total_s={local_block['total_latency_s']:.2f} "
                f"cloud_total_s="
                + (
                    f"{cloud_block['total_latency_s']:.2f}"
                    if cloud_block and "error" not in cloud_block
                    else "-"
                )
            )
        except Exception as exc:
            failure_count += 1
            print(f"- {qid}: error={exc}")
            results.append({"id": qid, "question": question, "error": str(exc)})

    ok_results = [r for r in results if "error" not in r]
    local_blocks = [r["local"] for r in ok_results if r.get("local")]
    cloud_blocks = [r["cloud"] for r in ok_results if r.get("cloud") and "error" not in r["cloud"]]

    summary = {
        "questions_requested": len(questions),
        "questions_processed": len(results),
        "success_count": success_count,
        "failure_count": failure_count,
        "cloud_compared": cloud_enabled,
        "cloud_note": None if cloud_enabled else cloud_reason,
        "local": _aggregate_blocks(local_blocks),
        "cloud": _aggregate_blocks(cloud_blocks) if cloud_blocks else None,
    }

    cloud_retrieval_label = (
        f"vector ({probe_run.embedding_model}, cloud embeddings)"
        if cloud_retrieval == "vector"
        else "lexical (shared local context)"
    )
    output = {
        "mode": "day28_local_vs_cloud_rag",
        "db": _display_path(db_path),
        "dataset": _display_path(dataset_path),
        "strategy_filter": args.strategy,
        "top_k": args.top_k,
        "cloud_retrieval_mode": cloud_retrieval,
        "local_pipeline": {
            "retrieval": "lexical (local, no network)",
            "generation_provider": provider,
        },
        "cloud_pipeline": {
            "retrieval": cloud_retrieval_label,
            "generation_provider": cloud_provider,
            "enabled": cloud_enabled,
        },
        "summary": summary,
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    local_agg = summary["local"]
    print("\nsummary [LOCAL]:")
    print(
        f"  kw_recall={local_agg['avg_keyword_recall']:.3f} "
        f"source_hit={local_agg['source_hit_rate']:.3f} "
        f"avg_total_s={local_agg['avg_total_latency_s']:.2f} "
        f"fallback={local_agg['fallback_count']}"
    )
    if summary["cloud"]:
        cloud_agg = summary["cloud"]
        print("summary [CLOUD]:")
        print(
            f"  kw_recall={cloud_agg['avg_keyword_recall']:.3f} "
            f"source_hit={cloud_agg['source_hit_rate']:.3f} "
            f"avg_total_s={cloud_agg['avg_total_latency_s']:.2f} "
            f"fallback={cloud_agg['fallback_count']}"
        )
    else:
        print(f"summary [CLOUD]: skipped ({cloud_reason})")
    print(f"success={success_count} failure={failure_count}")
    print(f"report: {_display_path(output_path)}")
    return 0


def _median(values: list[float]) -> float | None:
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    n = len(clean)
    mid = n // 2
    return clean[mid] if n % 2 else (clean[mid - 1] + clean[mid]) / 2


def _optimize_settings() -> tuple[GenerationSettings, GenerationSettings]:
    # num_ctx is intentionally left unset: changing it between arms forces Ollama
    # to reload the model from disk, which dominates wall-clock on CPU and masks
    # the real prompt/param effect. We tune sampling params only.
    baseline = GenerationSettings()
    optimized = GenerationSettings(
        temperature=OPTIMIZED_TEMPERATURE,
        top_p=OPTIMIZED_TOP_P,
        max_tokens=OPTIMIZED_MAX_TOKENS,
    )
    return baseline, optimized


def _optimize_pair(
    db_path: Path, question: str, strategy: str | None, provider: str
) -> tuple[RagTurn, RagTurn]:
    baseline_settings, optimized_settings = _optimize_settings()
    baseline_turn = run_local_rag(
        db_path=db_path,
        question=question,
        top_k=BASELINE_TOP_K,
        strategy=strategy,
        provider_name=provider,
        prompt_template=BASELINE_PROMPT,
        generation_settings=baseline_settings,
    )
    optimized_turn = run_local_rag(
        db_path=db_path,
        question=question,
        top_k=OPTIMIZED_TOP_K,
        strategy=strategy,
        provider_name=provider,
        prompt_template=OPTIMIZED_PROMPT,
        generation_settings=optimized_settings,
    )
    return baseline_turn, optimized_turn


def _optimize_warmup(provider: str, *, model_override: str | None = None) -> None:
    try:
        OllamaClient(provider_name=provider, model_override=model_override).generate(
            "warmup",
            temperature=0.0,
            max_tokens=WARMUP_MAX_TOKENS,
        )
    except Exception:
        pass


def _print_optimize_pair(baseline_turn: RagTurn, optimized_turn: RagTurn) -> None:
    print(f"\n== BASELINE (top_k={BASELINE_TOP_K}, default params, simple prompt) ==")
    _print_answer("baseline", baseline_turn, "lexical (baseline)")
    print(
        f"\n== OPTIMIZED (top_k={OPTIMIZED_TOP_K}, temperature={OPTIMIZED_TEMPERATURE}, "
        f"top_p={OPTIMIZED_TOP_P}, max_tokens={OPTIMIZED_MAX_TOKENS}, strict prompt) =="
    )
    _print_answer("optimized", optimized_turn, "lexical (optimized)")


def _repeated_block(
    *,
    db_path: Path,
    question: str,
    top_k: int,
    strategy: str | None,
    provider: str,
    prompt_template: str,
    settings: GenerationSettings,
    expected: list[str],
    expected_sources: list[str],
    retrieval_label: str,
    repeats: int,
    model_override: str | None = None,
) -> dict:
    blocks = []
    for _ in range(max(1, repeats)):
        turn = run_local_rag(
            db_path=db_path,
            question=question,
            top_k=top_k,
            strategy=strategy,
            provider_name=provider,
            prompt_template=prompt_template,
            generation_settings=settings,
            model_override=model_override,
        )
        blocks.append(_turn_block(turn, expected, expected_sources, retrieval_label))

    merged = dict(blocks[-1])
    merged["repeats"] = len(blocks)
    merged["retrieval_latency_s"] = _median([b["retrieval_latency_s"] for b in blocks]) or 0.0
    merged["generation_latency_s"] = _median([b["generation_latency_s"] for b in blocks]) or 0.0
    merged["total_latency_s"] = _median([b["total_latency_s"] for b in blocks]) or 0.0
    merged["tokens_per_sec"] = _median([b["tokens_per_sec"] for b in blocks])
    merged["keyword_recall"] = sum(b["keyword_recall"] for b in blocks) / len(blocks)
    merged["source_hit"] = (sum(1 for b in blocks if b["source_hit"]) / len(blocks)) >= 0.5
    merged["sources_format_ok"] = (
        sum(1 for b in blocks if b["sources_format_ok"]) / len(blocks)
    ) >= 0.5
    return merged


def _probe_model(
    db_path: Path, question: str, strategy: str | None, provider: str, model_id: str
) -> str | None:
    try:
        run_local_rag(
            db_path=db_path,
            question=question or "warmup",
            top_k=OPTIMIZED_TOP_K,
            strategy=strategy,
            provider_name=provider,
            prompt_template=OPTIMIZED_PROMPT,
            generation_settings=GenerationSettings(max_tokens=16),
            model_override=model_id,
        )
        return None
    except (OllamaClientError, RuntimeError) as exc:
        return str(exc)


def _run_optimize(args: argparse.Namespace) -> int:
    provider = _validate_local_provider(args.provider)
    db_path = Path(args.db)

    if args.interactive:
        _optimize_warmup(provider)
        print(
            "Interactive optimize mode (baseline vs optimized). "
            "Type a question; empty line or 'exit'/'quit' to stop."
        )
        while True:
            try:
                question = input("\nquestion> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not question or question.lower() in {"exit", "quit"}:
                break
            try:
                baseline_turn, optimized_turn = _optimize_pair(
                    db_path, question, args.strategy, provider
                )
            except (RuntimeError, ValueError) as exc:
                print(f"error: {exc}")
                continue
            _print_optimize_pair(baseline_turn, optimized_turn)
        return 0

    if args.question is not None and str(args.question).strip():
        question = str(args.question).strip()
        _optimize_warmup(provider)
        baseline_turn, optimized_turn = _optimize_pair(db_path, question, args.strategy, provider)
        _print_optimize_pair(baseline_turn, optimized_turn)
        return 0

    dataset_path = Path(args.dataset)
    output_path = Path(args.output)
    repeats = max(1, args.repeats)

    questions = _read_questions(dataset_path)
    if args.limit is not None and args.limit >= 0:
        questions = questions[: args.limit]

    if questions:
        _optimize_warmup(provider)

    quant_model = args.quant_model
    quant_available = False
    if quant_model:
        probe_question = str(questions[0].get("question", "")).strip() if questions else "warmup"
        quant_skip_reason = _probe_model(
            db_path, probe_question, args.strategy, provider, quant_model
        )
        quant_available = quant_skip_reason is None
        if not quant_available:
            print(
                f"quantization comparison skipped: {quant_model} unavailable "
                f"({quant_skip_reason}). Pull it first: ollama pull {quant_model}"
            )

    baseline_settings, optimized_settings = _optimize_settings()

    results: list[dict] = []
    success_count = 0
    failure_count = 0

    for item in questions:
        qid = str(item.get("id", "unknown"))
        question = str(item.get("question", "")).strip()
        expected = [str(v) for v in item.get("expected", [])]
        expected_sources = [str(v) for v in item.get("expected_sources", [])]
        if not question:
            failure_count += 1
            continue

        try:
            baseline_block = _repeated_block(
                db_path=db_path,
                question=question,
                top_k=BASELINE_TOP_K,
                strategy=args.strategy,
                provider=provider,
                prompt_template=BASELINE_PROMPT,
                settings=baseline_settings,
                expected=expected,
                expected_sources=expected_sources,
                retrieval_label=f"lexical (baseline, top_k={BASELINE_TOP_K})",
                repeats=repeats,
            )
            optimized_block = _repeated_block(
                db_path=db_path,
                question=question,
                top_k=OPTIMIZED_TOP_K,
                strategy=args.strategy,
                provider=provider,
                prompt_template=OPTIMIZED_PROMPT,
                settings=optimized_settings,
                expected=expected,
                expected_sources=expected_sources,
                retrieval_label=f"lexical (optimized, top_k={OPTIMIZED_TOP_K})",
                repeats=repeats,
            )
            results.append(
                {
                    "id": qid,
                    "question": question,
                    "expected": expected,
                    "expected_sources": expected_sources,
                    "baseline": baseline_block,
                    "optimized": optimized_block,
                }
            )
            success_count += 1
            print(
                f"- {qid}: base_kw={baseline_block['keyword_recall']:.2f} "
                f"opt_kw={optimized_block['keyword_recall']:.2f} "
                f"base_s={baseline_block['total_latency_s']:.2f} "
                f"opt_s={optimized_block['total_latency_s']:.2f}"
            )
        except Exception as exc:
            failure_count += 1
            print(f"- {qid}: error={exc}")
            results.append({"id": qid, "question": question, "error": str(exc)})

    # Quant arm runs as its own pass (not interleaved) so Ollama swaps the
    # model from disk only once, not on every question.
    if quant_available:
        print(f"\nrunning quant arm ({quant_model})...")
        for row in results:
            if "error" in row:
                continue
            try:
                quant_block = _repeated_block(
                    db_path=db_path,
                    question=row["question"],
                    top_k=OPTIMIZED_TOP_K,
                    strategy=args.strategy,
                    provider=provider,
                    prompt_template=OPTIMIZED_PROMPT,
                    settings=optimized_settings,
                    expected=row["expected"],
                    expected_sources=row["expected_sources"],
                    retrieval_label=f"lexical (quant, top_k={OPTIMIZED_TOP_K})",
                    repeats=repeats,
                    model_override=quant_model,
                )
                row["quant"] = quant_block
                print(
                    f"- {row['id']}: quant_kw={quant_block['keyword_recall']:.2f} "
                    f"quant_s={quant_block['total_latency_s']:.2f}"
                )
            except Exception as exc:
                print(f"- {row['id']}: quant_error={exc}")

    ok_results = [row for row in results if "error" not in row]
    baseline_blocks = [row["baseline"] for row in ok_results]
    optimized_blocks = [row["optimized"] for row in ok_results]
    quant_blocks = [row["quant"] for row in ok_results if "quant" in row]

    summary = {
        "questions_requested": len(questions),
        "questions_processed": len(results),
        "success_count": success_count,
        "failure_count": failure_count,
        "repeats_per_arm": repeats,
        "baseline": _aggregate_blocks(baseline_blocks),
        "optimized": _aggregate_blocks(optimized_blocks),
    }
    if quant_available:
        summary["quant"] = _aggregate_blocks(quant_blocks)

    output = {
        "mode": "day29_local_optimization",
        "db": _display_path(db_path),
        "dataset": _display_path(dataset_path),
        "strategy_filter": args.strategy,
        "local_provider": provider,
        "baseline_config": {
            "prompt_template": "BASELINE_PROMPT",
            "top_k": BASELINE_TOP_K,
            "temperature": None,
            "top_p": None,
            "max_tokens": None,
        },
        "optimized_config": {
            "prompt_template": "OPTIMIZED_PROMPT",
            "top_k": OPTIMIZED_TOP_K,
            "temperature": OPTIMIZED_TEMPERATURE,
            "top_p": OPTIMIZED_TOP_P,
            "max_tokens": OPTIMIZED_MAX_TOKENS,
        },
        "quant_config": (
            {"model": quant_model, "based_on": "optimized_config"} if quant_available else None
        ),
        "summary": summary,
        "results": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    def _print_summary(label: str, agg: dict) -> None:
        tps = agg["avg_tokens_per_sec"]
        tps_text = f"{tps:.1f}" if tps is not None else "n/a"
        print(f"summary [{label}]:")
        print(
            f"  kw_recall={agg['avg_keyword_recall']:.3f} "
            f"source_hit={agg['source_hit_rate']:.3f} "
            f"avg_total_s={agg['avg_total_latency_s']:.2f} "
            f"tokens_per_sec={tps_text} "
            f"avg_chars={agg['avg_answer_chars']:.1f} "
            f"sources_fmt={agg['sources_format_rate']:.2f}"
        )

    print(f"\nrepeats_per_arm={repeats} (median latency/tokens_per_sec, rate for quality fields)")
    _print_summary("BASELINE", summary["baseline"])
    _print_summary("OPTIMIZED", summary["optimized"])
    if quant_available:
        _print_summary(f"QUANT={quant_model}", summary["quant"])
    print(f"success={success_count} failure={failure_count}")
    print(f"report: {_display_path(output_path)}")
    return 0


def run() -> int:
    _ensure_console_utf8()
    args = _parse_args()
    try:
        if args.command == "ask":
            return _run_ask(args)
        if args.command == "compare":
            return _run_compare(args)
        if args.command == "eval":
            return _run_eval(args)
        if args.command == "optimize":
            return _run_optimize(args)
        raise ValueError(f"Unsupported command: {args.command}")
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
