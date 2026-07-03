from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from week_05.rag_qa import QaAnswer, answer_plain, answer_rag


@dataclass(frozen=True)
class AgentResult:
    mode: str
    plain: QaAnswer | None = None
    rag: QaAnswer | None = None


def run_agent(
    question: str,
    *,
    mode: str,
    provider_name: str,
    db_path: Path,
    source_root: Path,
    strategy: str = "structure",
    top_k: int = 5,
    top_k_before: int | None = None,
    min_similarity: float = -1.0,
    use_mmr: bool = False,
    rewrite_query: bool = False,
    hallucination_threshold: float = 0.33,
    min_grounded_chunks: int = 1,
    max_quotes: int = 2,
    quote_max_chars: int = 140,
    temperature: float = 0.2,
    max_tokens: int | None = 500,
) -> AgentResult:
    normalized_mode = mode.strip().lower()
    if normalized_mode not in {"plain", "rag", "both"}:
        raise ValueError(f"Unsupported mode: {mode}")

    plain_result: QaAnswer | None = None
    rag_result: QaAnswer | None = None

    if normalized_mode in {"plain", "both"}:
        plain_result = answer_plain(
            question,
            provider_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    if normalized_mode in {"rag", "both"}:
        rag_result = answer_rag(
            question,
            provider_name,
            db_path,
            source_root,
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
        )

    return AgentResult(mode=normalized_mode, plain=plain_result, rag=rag_result)
