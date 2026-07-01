from __future__ import annotations

import json
from pathlib import Path

from week_05.eval import run_eval
from week_05.rag_qa import QaAnswer, answer_plain, answer_rag
from week_05.retrieval import RetrievalResult, RetrievedChunk


def test_plain_mode_has_no_context_injection() -> None:
    captured: dict[str, list[dict[str, str]]] = {}

    def fake_generator(
        _provider: str,
        messages: list[dict[str, str]],
        _temperature: float,
        _max_tokens: int | None,
    ) -> tuple[str, object | None, float, str]:
        captured["messages"] = messages
        return "plain-answer", {"total_tokens": 10}, 0.1, "fake-model"

    out = answer_plain("What is RAG?", "GPT-4o mini", generator=fake_generator)
    assert out.answer == "plain-answer"
    assert len(captured["messages"]) == 2
    assert "Context:" not in captured["messages"][1]["content"]


def test_rag_mode_returns_citations_and_truncates_context() -> None:
    captured: dict[str, list[dict[str, str]]] = {}
    long_text = "A" * 4000

    def fake_retriever(
        _db: Path,
        _src: Path,
        _question: str,
        _strategy: str,
        _top_k: int,
    ) -> RetrievalResult:
        return RetrievalResult(
            chunks=[
                RetrievedChunk(
                    chunk_id="c1",
                    source="week_05/corpus/lecture-05-notes.md",
                    title="lecture-05-notes",
                    section="heading:RAG",
                    strategy="structure",
                    score=0.9,
                    text=long_text,
                    start_char=0,
                    end_char=len(long_text),
                )
            ],
            run_id="run-1",
            embedding_model_used="text-embedding-3-small",
            retrieved_count=1,
            avg_score=0.9,
        )

    def fake_generator(
        _provider: str,
        messages: list[dict[str, str]],
        _temperature: float,
        _max_tokens: int | None,
    ) -> tuple[str, object | None, float, str]:
        captured["messages"] = messages
        return "RAG answer\nSources: [C1]", {"total_tokens": 12}, 0.2, "fake-model"

    out = answer_rag(
        "Explain RAG",
        "GPT-4o mini",
        Path("db.sqlite"),
        Path("week_05/corpus"),
        generator=fake_generator,
        retriever=fake_retriever,
        max_chars_per_chunk=500,
        max_total_context_chars=600,
    )
    assert out.citations
    assert out.citations[0].chunk_id == "c1"
    assert out.retrieval_run_id == "run-1"
    user_prompt = captured["messages"][1]["content"]
    assert "Context:" in user_prompt
    assert len(user_prompt) < 1300


def test_rag_mode_empty_retrieval_is_graceful() -> None:
    def fake_retriever(
        _db: Path,
        _src: Path,
        _question: str,
        _strategy: str,
        _top_k: int,
    ) -> RetrievalResult:
        return RetrievalResult(
            chunks=[],
            run_id="run-empty",
            embedding_model_used="text-embedding-3-small",
            retrieved_count=0,
            avg_score=0.0,
        )

    out = answer_rag(
        "Explain RAG",
        "GPT-4o mini",
        Path("db.sqlite"),
        Path("week_05/corpus"),
        retriever=fake_retriever,
    )
    assert out.retrieved_count == 0
    assert out.citations == []
    assert "No relevant context found" in out.answer


def test_eval_scoring_is_deterministic(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / "lecture-01-notes.md").write_text("demo", encoding="utf-8")
    (corpus / "lecture-05-notes.md").write_text("demo", encoding="utf-8")
    dataset = tmp_path / "questions.json"
    dataset.write_text(
        json.dumps(
            [
                {
                    "id": "q1",
                    "question": "q1",
                    "expected": ["top_p", "temperature"],
                    "expected_sources": ["lecture-01-notes.md"],
                },
                {
                    "id": "q2",
                    "question": "q2",
                    "expected": ["rag"],
                    "expected_sources": ["lecture-05-notes.md"],
                },
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "results.json"

    def fake_plain(
        _question: str,
        provider_name: str,
        _temperature: float,
        _max_tokens: int | None,
    ) -> QaAnswer:
        return QaAnswer(
            mode="plain",
            question="q",
            answer="temperature only",
            provider=provider_name,
            model="m",
            latency_s=0.1,
            usage={},
            citations=[],
            retrieval_run_id=None,
            retrieval_embedding_model=None,
            retrieved_count=0,
            avg_retrieval_score=0.0,
        )

    def fake_rag(
        question: str,
        provider_name: str,
        _db_path: Path,
        _source_root: Path,
        _strategy: str,
        _top_k: int,
        _temperature: float,
        _max_tokens: int | None,
    ) -> QaAnswer:
        answer = "top_p and temperature" if question == "q1" else "rag"
        source = "week_05/corpus/lecture-01-notes.md" if question == "q1" else "other.md"
        return QaAnswer(
            mode="rag",
            question=question,
            answer=answer,
            provider=provider_name,
            model="m",
            latency_s=0.2,
            usage={},
            citations=[
                type(
                    "TmpCitation",
                    (),
                    {
                        "chunk_id": "c1",
                        "source": source,
                        "title": "t",
                        "section": "s",
                        "score": 0.9,
                    },
                )()
            ],
            retrieval_run_id="run",
            retrieval_embedding_model="embed-model",
            retrieved_count=1,
            avg_retrieval_score=0.9,
        )

    report = run_eval(
        dataset_path=dataset,
        output_path=output,
        provider_name="GPT-4o mini",
        db_path=tmp_path / "db.sqlite",
        source_root=corpus,
        plain_fn=fake_plain,
        rag_fn=fake_rag,
    )
    assert report.summary.questions_total == 2
    assert report.summary.questions_run == 2
    assert report.summary.avg_keyword_recall_plain == 0.25
    assert report.summary.avg_keyword_recall_rag == 1.0
    assert report.summary.rag_source_hit_rate == 0.5
    assert output.exists()
