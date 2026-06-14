from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from week_02.memory import Memory, Msg

SummarizeFn = Callable[[list[Msg], str | None], tuple[str, Any]]
ExtractFn = Callable[[list[Msg], dict], tuple[dict, Any]]

_TRIVIAL_STOP = {"ok", "ок", "да", "нет", "спасибо", "дальше", "next", "go", "yes", "no"}


@dataclass
class PolicyResult:
    changed: bool
    usage: Any | None = None
    usage_model_id: str | None = None


@dataclass
class CompressionResult(PolicyResult):
    dropped: int = 0


@dataclass
class FactsResult(PolicyResult):
    facts_count: int = 0


class ContextPolicy(Protocol):
    def compress_if_needed(self, memory: Memory) -> PolicyResult: ...
    def build_messages(self, memory: Memory, system_prompt: str | None) -> list[Msg]: ...
    def reset_state(self) -> None: ...


class SlidingWindowPolicy:
    def __init__(self, max_tokens: int = 500) -> None:
        self.max_tokens = max_tokens
        self.last_dropped: int = 0

    def compress_if_needed(self, memory: Memory) -> PolicyResult:
        return PolicyResult(changed=False)

    def build_messages(self, memory: Memory, system_prompt: str | None) -> list[Msg]:
        self.last_dropped = 0
        msgs: list[Msg] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.extend(memory.history())

        # 1 token ≈ 4 chars — rough heuristic for demo context limit
        char_budget = self.max_tokens * 4
        total_chars = sum(len(m["content"]) for m in msgs)
        start = 1 if msgs and msgs[0]["role"] == "system" else 0

        while total_chars > char_budget and start < len(msgs) - 1:
            total_chars -= len(msgs[start]["content"])
            msgs.pop(start)
            self.last_dropped += 1

        if start < len(msgs) - 1 and msgs[start]["role"] == "assistant":
            msgs.pop(start)
            self.last_dropped += 1

        return msgs

    def reset_state(self) -> None:
        pass


class SummaryPolicy:
    def __init__(
        self,
        summarize_fn: SummarizeFn,
        summary_path: Path,
        summary_model_id: str,
        keep_last: int = 10,
        chunk_size: int = 10,
    ) -> None:
        self._summarize_fn = summarize_fn
        self.summary_path = summary_path
        self.summary_model_id = summary_model_id
        self.keep_last = keep_last
        self.chunk_size = chunk_size
        self.summary: str | None = None
        self.compressed_up_to: int = 0
        self._load()

    def _load(self) -> None:
        if not self.summary_path.exists():
            return
        try:
            data = json.loads(self.summary_path.read_text(encoding="utf-8"))
            self.summary = data.get("summary")
            self.compressed_up_to = data.get("compressed_up_to", 0)
        except Exception:
            self.summary = None
            self.compressed_up_to = 0

    def _save(self) -> None:
        self.summary_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"summary": self.summary, "compressed_up_to": self.compressed_up_to}
        self.summary_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def compress_if_needed(self, memory: Memory) -> CompressionResult:
        hist = memory.history()
        end = max(0, len(hist) - self.keep_last)
        if end <= self.compressed_up_to:
            return CompressionResult(changed=False)
        pending = hist[self.compressed_up_to : end]
        if len(pending) < self.chunk_size:
            return CompressionResult(changed=False)
        old_summary = self.summary
        old_cursor = self.compressed_up_to
        try:
            new_summary, usage = self._summarize_fn(pending, self.summary)
            self.summary = new_summary
            self.compressed_up_to = end
            self._save()
        except Exception:
            self.summary = old_summary
            self.compressed_up_to = old_cursor
            return CompressionResult(changed=False)
        return CompressionResult(
            changed=True,
            usage=usage,
            dropped=len(pending),
            usage_model_id=self.summary_model_id,
        )

    def build_messages(self, memory: Memory, system_prompt: str | None) -> list[Msg]:
        hist = memory.history()
        msgs: list[Msg] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        if self.summary:
            msgs.append(
                {"role": "system", "content": f"Previous conversation summary:\n{self.summary}"}
            )
        msgs.extend(hist[self.compressed_up_to :])
        return msgs

    def reset_state(self) -> None:
        self.summary = None
        self.compressed_up_to = 0
        if self.summary_path.exists():
            self.summary_path.unlink()


class FactsPolicy:
    def __init__(
        self,
        extract_fn: ExtractFn,
        facts_path: Path,
        facts_model_id: str,
        keep_last: int = 10,
    ) -> None:
        self._extract_fn = extract_fn
        self.facts_path = facts_path
        self.facts_model_id = facts_model_id
        self.keep_last = keep_last
        self.facts: dict = {}
        self._load()

    def _load(self) -> None:
        if not self.facts_path.exists():
            return
        try:
            data = json.loads(self.facts_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.facts = data
        except Exception:
            self.facts = {}

    def _save(self) -> None:
        self.facts_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.facts_path.parent,
            delete=False,
            suffix=".tmp",
        )
        try:
            json.dump(self.facts, tmp, ensure_ascii=False, indent=2)
            tmp_path = Path(tmp.name)
        finally:
            tmp.close()
        tmp_path.replace(self.facts_path)

    def _is_trivial(self, memory: Memory) -> bool:
        hist = memory.history()
        last_user = next((m["content"] for m in reversed(hist) if m["role"] == "user"), "")
        text = last_user.strip()
        # cost optimization: skip extraction for very short or stop-listed messages
        return len(text) < 12 or text.lower() in _TRIVIAL_STOP

    def compress_if_needed(self, memory: Memory) -> FactsResult:
        if self._is_trivial(memory):
            return FactsResult(changed=False)
        hist = memory.history()
        old_facts = dict(self.facts)
        try:
            new_facts, usage = self._extract_fn(hist, self.facts)
            self.facts = new_facts
            self._save()
        except Exception:
            self.facts = old_facts
            return FactsResult(changed=False)
        return FactsResult(
            changed=True,
            usage=usage,
            usage_model_id=self.facts_model_id,
            facts_count=len(self.facts),
        )

    def build_messages(self, memory: Memory, system_prompt: str | None) -> list[Msg]:
        msgs: list[Msg] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        if not self.facts:
            # coverage invariant: no facts yet → full history, nothing dropped
            msgs.extend(memory.history())
            return msgs
        facts_lines = "\n".join(f"{k}: {v}" for k, v in self.facts.items())
        msgs.append({"role": "system", "content": f"Known facts:\n{facts_lines}"})
        msgs.extend(memory.history()[-self.keep_last :])
        return msgs

    def reset_state(self) -> None:
        self.facts = {}
        if self.facts_path.exists():
            self.facts_path.unlink()
