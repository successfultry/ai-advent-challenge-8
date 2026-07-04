from __future__ import annotations

import json
from pathlib import Path

import pytest

from week_05.chat.runner import run_chat_turn
from week_05.chat.scenarios import run_chat_scenario
from week_05.chat.session import (
    ChatSession,
    ChatTurn,
    SourceRef,
    load_session,
    new_session,
    save_session,
)
from week_05.chat.state import render_task_state, update_task_state
from week_05.rag_qa import Citation, QaAnswer


def test_task_state_updates_goal_constraints_terms_and_clarifications() -> None:
    state = update_task_state(
        update_task_state(
            update_task_state(new_session().task_state, "цель: сделать демо по rag"),
            "ограничение: отвечай кратко",
        ),
        "уточню: на русском языке, термин grounded = подтвержденный ответ",
    )
    assert state.goal == "сделать демо по rag"
    assert "отвечай кратко" in state.constraints
    assert any("уточню" in item.lower() for item in state.user_clarifications)
    assert state.fixed_terms.get("grounded") == "подтвержденный ответ"
    assert "Goal:" in render_task_state(state)


def test_session_save_load_roundtrip(tmp_path: Path) -> None:
    session = ChatSession(
        session_id="chat-1",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        task_state=new_session().task_state,
        turns=[
            ChatTurn(
                role="assistant",
                text="hello",
                sources=[SourceRef(chunk_id="c1", source="s", section="sec", score=0.9)],
                grounded=True,
                fallback_reason=None,
                rewritten_query=None,
            )
        ],
    )
    path = tmp_path / "chat.json"
    save_session(path, session)
    restored = load_session(path)
    assert restored.session_id == "chat-1"
    assert restored.turns[0].sources[0].chunk_id == "c1"


def test_run_chat_turn_appends_user_and_assistant_and_saves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    def fake_answer_rag(*args: object, **kwargs: object) -> QaAnswer:
        calls["question"] = args[0]
        calls["chat_history"] = kwargs.get("chat_history")
        return QaAnswer(
            mode="rag",
            question=str(args[0]),
            answer="answer",
            provider="GPT-4o mini",
            model="m",
            latency_s=0.1,
            usage=None,
            citations=[Citation(chunk_id="c1", source="a.md", title="a", section="s", score=0.8)],
            retrieved_count=1,
            avg_retrieval_score=0.8,
            grounded=True,
            fallback_reason=None,
        )

    monkeypatch.setattr("week_05.chat.runner.answer_rag", fake_answer_rag)
    result = run_chat_turn(
        user_message="цель: сделать демо",
        provider_name="GPT-4o mini",
        db_path=tmp_path / "db.sqlite",
        source_root=tmp_path / "corpus",
        sessions_dir=tmp_path / "sessions",
        session_id="demo-session",
    )
    assert calls["question"] == "цель: сделать демо"
    chat_history = calls["chat_history"]
    assert isinstance(chat_history, list)
    assert result.session.turns[0].role == "user"
    assert result.session.turns[1].role == "assistant"
    assert result.session.turns[1].sources
    assert result.session_path.exists()


def test_run_chat_scenario_reports_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = tmp_path / "scenario.json"
    scenario.write_text(
        json.dumps(
            {
                "id": "sc1",
                "expected_goal_keywords": ["rag"],
                "messages": ["goal: rag demo", "what is retrieval?"],
            }
        ),
        encoding="utf-8",
    )

    class _FakeRunResult:
        def __init__(
            self, grounded: bool, fallback_reason: str | None, *, has_citations: bool = True
        ) -> None:
            self.session = ChatSession(
                session_id="sc1",
                created_at="x",
                updated_at="x",
                task_state=update_task_state(new_session().task_state, "goal: rag demo"),
                turns=[],
            )
            citations = (
                [
                    Citation(
                        chunk_id="c1",
                        source="a.md",
                        title="a",
                        section="s",
                        score=0.9,
                    )
                ]
                if has_citations
                else []
            )
            self.answer = QaAnswer(
                mode="rag",
                question="q",
                answer="rag answer",
                provider="GPT-4o mini",
                model="m",
                latency_s=0.1,
                usage=None,
                citations=citations,
                retrieved_count=1,
                avg_retrieval_score=0.9,
                grounded=grounded,
                fallback_reason=fallback_reason,
            )
            self.session_path = Path("data/week_05/chat_sessions/sc1.json")

    responses = [
        _FakeRunResult(True, None, has_citations=True),
        _FakeRunResult(False, "low_similarity", has_citations=False),
    ]
    sessions_dir = tmp_path / "sessions"
    stale_session = sessions_dir / "sc1.json"
    stale_session.parent.mkdir(parents=True, exist_ok=True)
    stale_session.write_text("{}", encoding="utf-8")
    session_exists_before_turn: list[bool] = []

    def fake_run_chat_turn(**_kwargs: object) -> _FakeRunResult:
        session_exists_before_turn.append(stale_session.exists())
        return responses.pop(0)

    monkeypatch.setattr("week_05.chat.scenarios.run_chat_turn", fake_run_chat_turn)
    report = run_chat_scenario(
        scenario_path=scenario,
        provider_name="GPT-4o mini",
        db_path=tmp_path / "db.sqlite",
        source_root=tmp_path / "corpus",
        sessions_dir=sessions_dir,
    )
    assert report.turns_total == 2
    assert report.source_presence_rate == 1.0
    assert report.fallback_count == 1
    assert report.grounded_source_rate == 1.0
    assert session_exists_before_turn == [False, False]
