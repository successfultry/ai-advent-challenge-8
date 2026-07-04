from __future__ import annotations

import json
from pathlib import Path

import pytest

import week_05.eval as eval_module
from week_05.eval import EvalProfileConfig, run_eval, run_eval_comparison
from week_05.rag_qa import QaAnswer, Quote, answer_plain, answer_rag
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
    assert out.quotes
    assert out.citations[0].chunk_id == "c1"
    assert out.quotes[0].chunk_id == "c1"
    assert out.grounded is True
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
    assert out.quotes == []
    assert out.grounded is False
    assert out.fallback_reason == "no_context"
    assert "Не знаю на основе текущего контекста" in out.answer


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
        quote_text = "top_p and temperature" if question == "q1" else "rag"
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
            quotes=[
                Quote(
                    chunk_id="c1",
                    source=source,
                    title="t",
                    section="s",
                    score=0.9,
                    text=quote_text,
                )
            ],
            retrieval_run_id="run",
            retrieval_embedding_model="embed-model",
            retrieved_count=1,
            avg_retrieval_score=0.9,
            grounded=True,
            fallback_reason=None,
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
    assert report.summary.answers_with_sources_rate == 1.0
    assert report.summary.answers_with_quotes_rate == 1.0
    assert report.summary.avg_quote_keyword_overlap == 1.0
    assert report.summary.fallback_rate == 0.0
    assert output.exists()


def test_rag_rewrite_passes_rewritten_question_to_retriever() -> None:
    captured: dict[str, object] = {}

    def fake_retriever(
        _db: Path,
        _src: Path,
        question: str,
        _strategy: str,
        _top_k: int,
    ) -> RetrievalResult:
        captured["retriever_question"] = question
        return RetrievalResult(
            chunks=[],
            run_id="run-empty",
            embedding_model_used="text-embedding-3-small",
            retrieved_count=0,
            avg_score=0.0,
        )

    def fake_generator(
        _provider: str,
        messages: list[dict[str, str]],
        _temperature: float,
        _max_tokens: int | None,
    ) -> tuple[str, object | None, float, str]:
        if "Rewrite the user question" in messages[0]["content"]:
            return "rewritten terms query", None, 0.01, "fake-model"
        return "answer", None, 0.01, "fake-model"

    out = answer_rag(
        "что такое rag",
        "GPT-4o mini",
        Path("db.sqlite"),
        Path("week_05/corpus"),
        rewrite_query=True,
        generator=fake_generator,
        retriever=fake_retriever,
    )
    assert captured["retriever_question"] == "rewritten terms query"
    assert out.rewritten_query == "rewritten terms query"
    assert out.query_used == "rewritten terms query"


def test_rag_includes_chat_history_in_generation_messages() -> None:
    captured: dict[str, list[dict[str, str]]] = {}

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
                    text="chunk text",
                    start_char=0,
                    end_char=10,
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
        return "answer\nSources: [C1]", None, 0.01, "fake-model"

    out = answer_rag(
        "what is rag",
        "GPT-4o mini",
        Path("db.sqlite"),
        Path("week_05/corpus"),
        generator=fake_generator,
        retriever=fake_retriever,
        chat_history=[
            {"role": "system", "content": "Task state: goal=rag"},
            {"role": "user", "content": "Earlier question"},
            {"role": "assistant", "content": "Earlier answer"},
        ],
    )
    assert out.grounded is True
    messages = captured["messages"]
    assert messages[1]["content"] == "Task state: goal=rag"
    assert messages[2]["content"] == "Earlier question"
    assert messages[3]["content"] == "Earlier answer"


def test_quotes_are_substrings_of_chunk_text() -> None:
    chunk_text = "One deterministic quote lives in this chunk text."

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
                    score=0.92,
                    text=chunk_text,
                    start_char=0,
                    end_char=len(chunk_text),
                )
            ],
            run_id="run-1",
            embedding_model_used="text-embedding-3-small",
            retrieved_count=1,
            avg_score=0.92,
        )

    def fake_generator(
        _provider: str,
        _messages: list[dict[str, str]],
        _temperature: float,
        _max_tokens: int | None,
    ) -> tuple[str, object | None, float, str]:
        return "ok", None, 0.1, "fake-model"

    out = answer_rag(
        "Explain",
        "GPT-4o mini",
        Path("db.sqlite"),
        Path("week_05/corpus"),
        generator=fake_generator,
        retriever=fake_retriever,
    )
    assert out.quotes
    quote_text = out.quotes[0].text.replace("...", "")
    assert quote_text in " ".join(chunk_text.split())


def test_fallback_on_low_similarity() -> None:
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
                    score=0.20,
                    text="weak context",
                    start_char=0,
                    end_char=12,
                )
            ],
            run_id="run-low",
            embedding_model_used="text-embedding-3-small",
            retrieved_count=1,
            avg_score=0.20,
        )

    out = answer_rag(
        "Explain",
        "GPT-4o mini",
        Path("db.sqlite"),
        Path("week_05/corpus"),
        retriever=fake_retriever,
        hallucination_threshold=0.33,
    )
    assert out.grounded is False
    assert out.fallback_reason == "low_similarity"
    assert out.answer.startswith("Не знаю")


def test_eval_comparison_outputs_profile_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = tmp_path / "questions.json"
    dataset.write_text("[]", encoding="utf-8")
    output = tmp_path / "compare.json"

    def fake_run_eval(**kwargs: object) -> eval_module.EvalReport:
        profile = str(kwargs["profile_name"])
        summary = eval_module.EvalSummary(
            questions_total=10,
            questions_run=10,
            avg_keyword_recall_plain=0.4,
            avg_keyword_recall_rag=0.8 if profile == "improved" else 0.6,
            rag_source_hit_rate=0.9 if profile == "improved" else 0.7,
            answers_with_sources_rate=1.0,
            answers_with_quotes_rate=0.9 if profile == "improved" else 0.6,
            avg_quote_keyword_overlap=0.7 if profile == "improved" else 0.5,
            fallback_rate=0.1 if profile == "improved" else 0.0,
        )
        result = eval_module.EvalQuestionResult(
            id="q1",
            question="q1",
            keyword_recall_plain=0.0,
            keyword_recall_rag=1.0,
            source_hit=True,
            retrieved_count=4 if profile == "improved" else 5,
            avg_retrieval_score=0.5,
            has_sources=True,
            has_quotes=True,
            quote_keyword_overlap=1.0,
            grounded=True,
            fallback_reason=None,
            plain_answer="a",
            rag_answer="b",
        )
        return eval_module.EvalReport(
            profile=profile,
            provider="GPT-4o mini",
            strategy="structure",
            source_root="week_05/corpus",
            db_path="data/week_05/rag_index.sqlite",
            summary=summary,
            results=[result],
        )

    monkeypatch.setattr(eval_module, "run_eval", fake_run_eval)
    comparison = run_eval_comparison(
        dataset_path=dataset,
        output_path=output,
        provider_name="GPT-4o mini",
        db_path=tmp_path / "db.sqlite",
        source_root=tmp_path / "corpus",
        strategy="structure",
        profiles=[
            EvalProfileConfig(name="baseline", top_k=5),
            EvalProfileConfig(name="improved", top_k=5, rewrite_query=True),
        ],
    )
    assert len(comparison.profiles) == 2
    assert comparison.profiles[0].profile == "baseline"
    assert comparison.profiles[1].profile == "improved"
    assert output.exists()
