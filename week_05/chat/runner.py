from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from week_05.chat.session import (
    ChatSession,
    ChatTurn,
    SourceRef,
    append_turn,
    load_session,
    new_session,
    save_session,
    set_task_state,
)
from week_05.chat.state import render_task_state, update_task_state
from week_05.rag_qa import QaAnswer, answer_rag


@dataclass(frozen=True)
class ChatRunResult:
    session: ChatSession
    answer: QaAnswer
    session_path: Path


def _build_chat_history(
    session: ChatSession,
    *,
    history_limit: int,
    max_turn_chars: int,
    max_history_chars: int,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": f"Task state: {render_task_state(session.task_state)}"}
    ]
    turns = session.turns[-history_limit:] if history_limit > 0 else []
    for turn in turns:
        role = "assistant" if turn.role == "assistant" else "user"
        content = turn.text.strip()
        if len(content) > max_turn_chars:
            content = content[:max_turn_chars].rstrip() + "..."
        if content:
            messages.append({"role": role, "content": content})

    # Soft history budget: keep task-state + most recent turns.
    while True:
        total_chars = sum(len(msg["content"]) for msg in messages)
        if total_chars <= max_history_chars or len(messages) <= 2:
            break
        messages.pop(1)
    return messages


def _session_path(base_dir: Path, session_id: str) -> Path:
    return base_dir / f"{session_id}.json"


def _relativize(source: str) -> str:
    try:
        return Path(source).resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return source


def run_chat_turn(
    *,
    user_message: str,
    provider_name: str,
    db_path: Path,
    source_root: Path,
    sessions_dir: Path,
    session_id: str | None = None,
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
    max_turn_chars: int = 500,
    max_history_chars: int = 6000,
) -> ChatRunResult:
    if not user_message.strip():
        raise ValueError("User message must not be empty.")

    if session_id is not None:
        path = _session_path(sessions_dir, session_id)
        session = load_session(path) if path.exists() else new_session(session_id=session_id)
    else:
        session = new_session()
        path = _session_path(sessions_dir, session.session_id)

    session = append_turn(
        session,
        ChatTurn(
            role="user",
            text=user_message.strip(),
            sources=[],
            grounded=False,
            fallback_reason=None,
            rewritten_query=None,
        ),
    )
    session = set_task_state(session, update_task_state(session.task_state, user_message))
    chat_history = _build_chat_history(
        session,
        history_limit=history_limit,
        max_turn_chars=max_turn_chars,
        max_history_chars=max_history_chars,
    )

    answer = answer_rag(
        user_message.strip(),
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
        hallucination_threshold=hallucination_threshold,
        min_grounded_chunks=min_grounded_chunks,
        max_quotes=max_quotes,
        quote_max_chars=quote_max_chars,
        chat_history=chat_history,
    )

    assistant_sources = [
        SourceRef(
            chunk_id=citation.chunk_id,
            source=_relativize(citation.source),
            section=citation.section,
            score=citation.score,
            label=citation.label,
            used=citation.used,
        )
        for citation in answer.citations
    ]
    session = append_turn(
        session,
        ChatTurn(
            role="assistant",
            text=answer.answer,
            sources=assistant_sources,
            grounded=answer.grounded,
            fallback_reason=answer.fallback_reason,
            rewritten_query=answer.rewritten_query,
        ),
    )
    save_session(path, session)
    return ChatRunResult(session=session, answer=answer, session_path=path)
