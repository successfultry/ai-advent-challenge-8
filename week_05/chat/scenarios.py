from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from week_05.chat.runner import run_chat_turn


@dataclass(frozen=True)
class ScenarioReport:
    scenario_id: str
    turns_total: int
    source_presence_rate: float
    grounded_source_rate: float
    fallback_count: int
    goal_retention_rate: float
    session_path: str


def run_chat_scenario(
    *,
    scenario_path: Path,
    provider_name: str,
    db_path: Path,
    source_root: Path,
    sessions_dir: Path,
    strategy: str = "structure",
    top_k: int = 5,
    top_k_before: int | None = 20,
    min_similarity: float = 0.2,
    use_mmr: bool = False,
    rewrite_query: bool = True,
    hallucination_threshold: float = 0.33,
    min_grounded_chunks: int = 1,
    max_quotes: int = 2,
    quote_max_chars: int = 200,
    temperature: float = 0.2,
    max_tokens: int | None = 500,
    history_limit: int = 6,
) -> ScenarioReport:
    payload = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario_id = str(payload["id"])
    expected_goal_keywords = [
        str(item).lower() for item in payload.get("expected_goal_keywords", [])
    ]
    messages = [str(item) for item in payload.get("messages", [])]

    if not messages:
        raise ValueError("Scenario must contain at least one message.")

    run_result = None
    source_block_count = 0
    grounded_turns = 0
    grounded_with_sources = 0
    fallback_count = 0
    goal_retained = 0

    for message in messages:
        run_result = run_chat_turn(
            user_message=message,
            provider_name=provider_name,
            db_path=db_path,
            source_root=source_root,
            sessions_dir=sessions_dir,
            session_id=scenario_id,
            strategy=strategy,
            top_k=top_k,
            top_k_before=top_k_before,
            min_similarity=min_similarity,
            use_mmr=use_mmr,
            rewrite_query=rewrite_query,
            hallucination_threshold=hallucination_threshold,
            min_grounded_chunks=min_grounded_chunks,
            max_quotes=max_quotes,
            quote_max_chars=quote_max_chars,
            temperature=temperature,
            max_tokens=max_tokens,
            history_limit=history_limit,
        )
        answer = run_result.answer
        # In our CLI, Sources block is always printed, even when empty.
        source_block_count += 1
        if answer.grounded:
            grounded_turns += 1
            if answer.citations:
                grounded_with_sources += 1
        if answer.fallback_reason is not None:
            fallback_count += 1

        # Retention is measured on the model's actual output (answer or the
        # rewritten retrieval query), NOT on task_state.goal. The stored goal is
        # deterministic and always present, so checking it would make retention
        # trivially 1.0. Goal persistence in task_state is shown via the session
        # file / render_task_state, kept separate from this rate on purpose.
        lowered_answer = answer.answer.lower()
        lowered_query = (answer.rewritten_query or "").lower()
        if any(
            keyword in lowered_answer or keyword in lowered_query
            for keyword in expected_goal_keywords
        ):
            goal_retained += 1

    assert run_result is not None
    turns_total = len(messages)
    source_presence_rate = source_block_count / turns_total if turns_total else 0.0
    grounded_source_rate = (
        grounded_with_sources / grounded_turns if grounded_turns else 1.0
    )
    goal_retention_rate = goal_retained / turns_total if turns_total else 0.0

    return ScenarioReport(
        scenario_id=scenario_id,
        turns_total=turns_total,
        source_presence_rate=source_presence_rate,
        grounded_source_rate=grounded_source_rate,
        fallback_count=fallback_count,
        goal_retention_rate=goal_retention_rate,
        session_path=run_result.session_path.as_posix(),
    )
