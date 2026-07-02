from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from shared.client import get_client, timed_response
from week_05.retrieval import RetrievalResult, retrieve_chunks

GenerateFn = Callable[
    [str, list[dict[str, str]], float, int | None], tuple[str, object | None, float, str]
]
RetrieveFn = Callable[[Path, Path, str, str, int], RetrievalResult]

NO_CONTEXT_MESSAGE = "No relevant context found for selected strategy/run."


@dataclass(frozen=True)
class Citation:
    chunk_id: str
    source: str
    title: str
    section: str
    score: float


@dataclass(frozen=True)
class QaAnswer:
    mode: str
    question: str
    answer: str
    provider: str
    model: str
    latency_s: float
    usage: object | None
    citations: list[Citation]
    retrieval_run_id: str | None
    retrieval_embedding_model: str | None
    retrieved_count: int
    avg_retrieval_score: float
    retrieved_before: int = 0
    retrieved_after_threshold: int = 0
    rewritten_query: str | None = None
    query_used: str | None = None


def _default_generate(
    provider_name: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int | None,
) -> tuple[str, object | None, float, str]:
    client, model_id = get_client(provider_name)
    content, _reason, usage, elapsed = timed_response(
        client,
        model_id,
        messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return content, usage, elapsed, model_id


def _default_retrieve(
    db_path: Path,
    source_root: Path,
    question: str,
    strategy: str,
    top_k: int,
    top_k_before: int | None = None,
    min_similarity: float = -1.0,
    use_mmr: bool = False,
    rewritten_query: str | None = None,
) -> RetrievalResult:
    return retrieve_chunks(
        db_path=db_path,
        source_root=source_root,
        question=question,
        strategy=strategy,
        top_k=top_k,
        top_k_before=top_k_before,
        min_similarity=min_similarity,
        use_mmr=use_mmr,
        rewritten_query=rewritten_query,
    )


def _rewrite_query(
    question: str,
    provider_name: str,
    *,
    generator: GenerateFn,
) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "Rewrite the user question into a short focused search query. "
                "Keep the key terms from the question itself and add at most 2-3 close "
                "synonyms or directly related terms. Do NOT introduce unrelated topics. "
                "Keep it concise. Return ONLY the rewritten query."
            ),
        },
        {"role": "user", "content": f"Question: {question}"},
    ]
    content, _usage, _elapsed, _model = generator(provider_name, messages, 0.0, 120)
    rewritten = content.strip()
    return rewritten if rewritten else question


def answer_plain(
    question: str,
    provider_name: str,
    *,
    temperature: float = 0.2,
    max_tokens: int | None = 500,
    generator: GenerateFn | None = None,
) -> QaAnswer:
    normalized_question = question.strip()
    if not normalized_question:
        raise ValueError("Question must not be empty.")
    call_model = generator or _default_generate
    messages = [
        {"role": "system", "content": "Answer the question directly. Be concise."},
        {"role": "user", "content": normalized_question},
    ]
    content, usage, elapsed, model_id = call_model(
        provider_name,
        messages,
        temperature,
        max_tokens,
    )
    return QaAnswer(
        mode="plain",
        question=normalized_question,
        answer=content,
        provider=provider_name,
        model=model_id,
        latency_s=elapsed,
        usage=usage,
        citations=[],
        retrieval_run_id=None,
        retrieval_embedding_model=None,
        retrieved_count=0,
        avg_retrieval_score=0.0,
    )


def answer_rag(
    question: str,
    provider_name: str,
    db_path: Path,
    source_root: Path,
    *,
    strategy: str = "structure",
    top_k: int = 5,
    top_k_before: int | None = None,
    min_similarity: float = -1.0,
    use_mmr: bool = False,
    rewrite_query: bool = False,
    temperature: float = 0.2,
    max_tokens: int | None = 500,
    max_chars_per_chunk: int = 1000,
    max_total_context_chars: int = 6000,
    generator: GenerateFn | None = None,
    retriever: RetrieveFn | None = None,
) -> QaAnswer:
    normalized_question = question.strip()
    if not normalized_question:
        raise ValueError("Question must not be empty.")

    call_model = generator or _default_generate
    query_used = normalized_question
    rewritten_query: str | None = None
    if rewrite_query:
        rewritten_query = _rewrite_query(
            normalized_question,
            provider_name,
            generator=call_model,
        )
        query_used = rewritten_query

    if retriever is None:
        retrieval = _default_retrieve(
            db_path,
            source_root,
            query_used,
            strategy,
            top_k,
            top_k_before=top_k_before,
            min_similarity=min_similarity,
            use_mmr=use_mmr,
            rewritten_query=rewritten_query,
        )
    else:
        retrieval = retriever(db_path, source_root, query_used, strategy, top_k)

    citations = [
        Citation(
            chunk_id=chunk.chunk_id,
            source=chunk.source,
            title=chunk.title,
            section=chunk.section,
            score=chunk.score,
        )
        for chunk in retrieval.chunks
    ]
    if not retrieval.chunks:
        return QaAnswer(
            mode="rag",
            question=normalized_question,
            answer=NO_CONTEXT_MESSAGE,
            provider=provider_name,
            model="n/a",
            latency_s=0.0,
            usage=None,
            citations=[],
            retrieval_run_id=retrieval.run_id,
            retrieval_embedding_model=retrieval.embedding_model_used,
            retrieved_count=0,
            avg_retrieval_score=0.0,
            retrieved_before=retrieval.retrieved_before,
            retrieved_after_threshold=retrieval.retrieved_after_threshold,
            rewritten_query=rewritten_query or retrieval.rewritten_query,
            query_used=query_used,
        )

    context_parts: list[str] = []
    used_chars = 0
    for idx, chunk in enumerate(retrieval.chunks, start=1):
        text = chunk.text.strip()
        if len(text) > max_chars_per_chunk:
            text = text[:max_chars_per_chunk].rstrip() + "..."
        if used_chars + len(text) > max_total_context_chars and context_parts:
            break
        used_chars += len(text)
        context_parts.append(
            f"[C{idx}] source={chunk.source} title={chunk.title} section={chunk.section} "
            f"chunk_id={chunk.chunk_id} score={chunk.score:.4f}\n{text}"
        )
    context_block = "\n\n".join(context_parts)

    messages = [
        {
            "role": "system",
            "content": (
                "Answer using ONLY the provided context. If context is insufficient, say so. "
                "End with 'Sources: [C1], [C3]' listing the chunk ids you used."
            ),
        },
        {
            "role": "user",
            "content": f"Question: {normalized_question}\n\nContext:\n{context_block}",
        },
    ]
    content, usage, elapsed, model_id = call_model(
        provider_name,
        messages,
        temperature,
        max_tokens,
    )
    return QaAnswer(
        mode="rag",
        question=normalized_question,
        answer=content,
        provider=provider_name,
        model=model_id,
        latency_s=elapsed,
        usage=usage,
        citations=citations,
        retrieval_run_id=retrieval.run_id,
        retrieval_embedding_model=retrieval.embedding_model_used,
        retrieved_count=retrieval.retrieved_count,
        avg_retrieval_score=retrieval.avg_score,
        retrieved_before=retrieval.retrieved_before,
        retrieved_after_threshold=retrieval.retrieved_after_threshold,
        rewritten_query=rewritten_query or retrieval.rewritten_query,
        query_used=query_used,
    )
