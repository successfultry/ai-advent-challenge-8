from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from week_05.rag_qa import QaAnswer, answer_plain, answer_rag

PlainAnswerFn = Callable[[str, str, float, int | None], QaAnswer]
RagAnswerFn = Callable[[str, str, Path, Path, str, int, float, int | None], QaAnswer]


@dataclass(frozen=True)
class EvalQuestion:
    id: str
    question: str
    expected: list[str]
    expected_sources: list[str]


@dataclass(frozen=True)
class EvalQuestionResult:
    id: str
    question: str
    keyword_recall_plain: float
    keyword_recall_rag: float
    source_hit: bool
    retrieved_count: int
    avg_retrieval_score: float
    plain_answer: str
    rag_answer: str


@dataclass(frozen=True)
class EvalSummary:
    questions_total: int
    questions_run: int
    avg_keyword_recall_plain: float
    avg_keyword_recall_rag: float
    rag_source_hit_rate: float


@dataclass(frozen=True)
class EvalReport:
    profile: str
    provider: str
    strategy: str
    source_root: str
    db_path: str
    summary: EvalSummary
    results: list[EvalQuestionResult]


@dataclass(frozen=True)
class EvalProfileConfig:
    name: str
    top_k: int
    top_k_before: int | None = None
    min_similarity: float = -1.0
    use_mmr: bool = False
    rewrite_query: bool = False


@dataclass(frozen=True)
class EvalProfileSummary:
    profile: str
    avg_keyword_recall_plain: float
    avg_keyword_recall_rag: float
    source_hit_rate: float
    avg_retrieved_final: float


@dataclass(frozen=True)
class EvalComparisonReport:
    provider: str
    strategy: str
    source_root: str
    db_path: str
    profiles: list[EvalProfileSummary]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _display_path(value: str | Path) -> str:
    path = Path(value)
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(value)


def _keyword_recall(expected: list[str], answer: str) -> float:
    if not expected:
        return 1.0
    answer_norm = _normalize_text(answer)
    hits = 0
    for keyword in expected:
        if _normalize_text(keyword) in answer_norm:
            hits += 1
    return hits / len(expected)


def _source_hit(expected_sources: list[str], rag: QaAnswer) -> bool:
    if not expected_sources:
        return False
    rag_sources = [citation.source for citation in rag.citations]
    for expected in expected_sources:
        expected_norm = expected.replace("\\", "/")
        for source in rag_sources:
            source_norm = source.replace("\\", "/")
            if Path(source_norm).name == expected_norm or source_norm.endswith(expected_norm):
                return True
    return False


def load_questions(dataset_path: Path, source_root: Path) -> list[EvalQuestion]:
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    questions = [
        EvalQuestion(
            id=str(item["id"]),
            question=str(item["question"]),
            expected=[str(value) for value in item.get("expected", [])],
            expected_sources=[str(value) for value in item.get("expected_sources", [])],
        )
        for item in payload
    ]
    for question in questions:
        for expected_source in question.expected_sources:
            expected_path = source_root / expected_source
            if not expected_path.exists():
                raise ValueError(
                    f"Dataset source does not exist: {expected_source} (question {question.id})"
                )
    return questions


def run_eval(
    *,
    dataset_path: Path,
    output_path: Path,
    provider_name: str,
    db_path: Path,
    source_root: Path,
    strategy: str = "structure",
    top_k: int = 5,
    profile_name: str = "default",
    top_k_before: int | None = None,
    min_similarity: float = -1.0,
    use_mmr: bool = False,
    rewrite_query: bool = False,
    limit: int | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = 500,
    plain_fn: PlainAnswerFn | None = None,
    rag_fn: RagAnswerFn | None = None,
) -> EvalReport:
    source_root = source_root.resolve()
    all_questions = load_questions(dataset_path, source_root)
    questions = all_questions
    if limit is not None and limit >= 0:
        questions = questions[:limit]
    call_plain = plain_fn or (
        lambda q, p, t, m: answer_plain(q, p, temperature=t, max_tokens=m)
    )
    results: list[EvalQuestionResult] = []
    for question in questions:
        plain = call_plain(question.question, provider_name, temperature, max_tokens)
        if rag_fn is None:
            rag = answer_rag(
                question.question,
                provider_name,
                db_path,
                source_root,
                strategy=strategy,
                top_k=top_k,
                top_k_before=top_k_before,
                min_similarity=min_similarity,
                use_mmr=use_mmr,
                rewrite_query=rewrite_query,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        else:
            rag = rag_fn(
                question.question,
                provider_name,
                db_path,
                source_root,
                strategy,
                top_k,
                temperature,
                max_tokens,
            )
        results.append(
            EvalQuestionResult(
                id=question.id,
                question=question.question,
                keyword_recall_plain=_keyword_recall(question.expected, plain.answer),
                keyword_recall_rag=_keyword_recall(question.expected, rag.answer),
                source_hit=_source_hit(question.expected_sources, rag),
                retrieved_count=rag.retrieved_count,
                avg_retrieval_score=rag.avg_retrieval_score,
                plain_answer=plain.answer,
                rag_answer=rag.answer,
            )
        )

    run_count = len(results)
    plain_avg = (
        sum(item.keyword_recall_plain for item in results) / run_count if run_count else 0.0
    )
    rag_avg = sum(item.keyword_recall_rag for item in results) / run_count if run_count else 0.0
    source_hit_rate = (
        sum(1 for item in results if item.source_hit) / run_count if run_count else 0.0
    )

    report = EvalReport(
        profile=profile_name,
        provider=provider_name,
        strategy=strategy,
        source_root=_display_path(source_root),
        db_path=_display_path(db_path),
        summary=EvalSummary(
            questions_total=len(all_questions),
            questions_run=run_count,
            avg_keyword_recall_plain=plain_avg,
            avg_keyword_recall_rag=rag_avg,
            rag_source_hit_rate=source_hit_rate,
        ),
        results=results,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def _profile_summary(report: EvalReport) -> EvalProfileSummary:
    run_count = len(report.results)
    avg_retrieved = (
        sum(item.retrieved_count for item in report.results) / run_count if run_count else 0.0
    )
    return EvalProfileSummary(
        profile=report.profile,
        avg_keyword_recall_plain=report.summary.avg_keyword_recall_plain,
        avg_keyword_recall_rag=report.summary.avg_keyword_recall_rag,
        source_hit_rate=report.summary.rag_source_hit_rate,
        avg_retrieved_final=avg_retrieved,
    )


def run_eval_comparison(
    *,
    dataset_path: Path,
    output_path: Path,
    provider_name: str,
    db_path: Path,
    source_root: Path,
    strategy: str,
    profiles: list[EvalProfileConfig],
    limit: int | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = 500,
) -> EvalComparisonReport:
    summaries: list[EvalProfileSummary] = []
    plain_cache: dict[str, QaAnswer] | None = None
    for profile in profiles:
        profile_plain_fn: PlainAnswerFn | None = None
        if plain_cache is not None:
            cache_ref = plain_cache

            def _cached_plain(
                question: str,
                provider_name_arg: str,
                _temperature: float,
                _max_tokens: int | None,
                _cache_ref: dict[str, QaAnswer] = cache_ref,
            ) -> QaAnswer:
                cached = _cache_ref.get(question)
                if cached is not None:
                    return cached
                return answer_plain(question, provider_name_arg, temperature=0.2, max_tokens=500)

            profile_plain_fn = _cached_plain

        profile_output = output_path.with_name(
            f"{output_path.stem}_{profile.name}{output_path.suffix}"
        )
        report = run_eval(
            dataset_path=dataset_path,
            output_path=profile_output,
            provider_name=provider_name,
            db_path=db_path,
            source_root=source_root,
            strategy=strategy,
            top_k=profile.top_k,
            profile_name=profile.name,
            top_k_before=profile.top_k_before,
            min_similarity=profile.min_similarity,
            use_mmr=profile.use_mmr,
            rewrite_query=profile.rewrite_query,
            limit=limit,
            temperature=temperature,
            max_tokens=max_tokens,
            plain_fn=profile_plain_fn,
        )
        summaries.append(_profile_summary(report))
        if plain_cache is None:
            plain_cache = {
                item.question: QaAnswer(
                    mode="plain",
                    question=item.question,
                    answer=item.plain_answer,
                    provider=provider_name,
                    model="cached",
                    latency_s=0.0,
                    usage=None,
                    citations=[],
                    retrieval_run_id=None,
                    retrieval_embedding_model=None,
                    retrieved_count=0,
                    avg_retrieval_score=0.0,
                )
                for item in report.results
            }

    comparison = EvalComparisonReport(
        provider=provider_name,
        strategy=strategy,
        source_root=_display_path(source_root),
        db_path=_display_path(db_path),
        profiles=summaries,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(asdict(comparison), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return comparison
