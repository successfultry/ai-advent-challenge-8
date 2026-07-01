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
    provider: str
    strategy: str
    source_root: str
    db_path: str
    summary: EvalSummary
    results: list[EvalQuestionResult]


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
    call_rag = rag_fn or (
        lambda q, p, db, src, strat, k, t, m: answer_rag(
            q,
            p,
            db,
            src,
            strategy=strat,
            top_k=k,
            temperature=t,
            max_tokens=m,
        )
    )

    results: list[EvalQuestionResult] = []
    for question in questions:
        plain = call_plain(question.question, provider_name, temperature, max_tokens)
        rag = call_rag(
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
