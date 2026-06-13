# Week 02 — Agent internals: context, memory, planning, tools

## Structure

```
week_02/
├── main.py        # entrypoint (argparse --user, --policy)
├── cli.py         # terminal UI (rich, chat loop)
├── agent.py       # Agent — orchestrator: Memory + Policy + LLM
├── memory.py      # Memory (Protocol), SessionMemory, FileMemory
├── context.py     # ContextPolicy (Protocol), SlidingWindow, Summary
├── stats.py       # TokenStats (session totals)
└── summarizer.py  # LLM-based summary generation
```

`Memory` is a `typing.Protocol` defining the interface (`add`, `history`, `pop_last`, `clear`).
`SessionMemory` stores history in RAM (lost on exit).
`FileMemory` stores history in `data/history_{user}.json` (persistent).

Providers and HTTP client live in `shared/` (imported from `shared.client` and `shared.config`).

## Run

```bash
# Default user (history_default.json)
uv run python -m week_02.main

# Specific user (history_john.json)
uv run python -m week_02.main --user=john
uv run python -m week_02.main -u alice
```

Each user has a separate history file in `data/`.

Requires a `.env` in the repo root with at least one key:

```
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...
```

## Day 6 — First Agent

Agent as a distinct entity. Not just an API call — the `Agent` class encapsulates:
- message assembly (`system_prompt` + history + new user input),
- streaming LLM call,
- memory update (`SessionMemory`) after each turn.

`system_prompt` is injected on the fly in `_build_messages()` and never stored in memory,
so `/clear` resets the conversation history without losing the agent's role.

`/switch` creates a new Agent with the same `memory` object — history survives model change.

CLI only knows `agent.ask_stream(text)` and `agent.reset()`.

### In-chat commands

| Command | Action |
|---------|--------|
| `/clear` | clear chat history |
| `/switch` | switch model (history preserved) |
| `/help` | show commands |
| `exit` / `quit` / `выход` | quit |

### Demo (for the video)

**Show streaming:**
```
What is a context window in LLMs?
```
Answer arrives token by token.

**Show agent remembers context:**
```
You: Tell me about Python in two sentences
You: How does it differ from Go?       <- agent knows what "it" refers to
```

**Show /switch preserves history:**
```
You: Tell me about Python in two sentences
/switch                                <- pick a different model
You: How does it differ from Go?       <- new model sees the same history
```

**Show /clear breaks context:**
```
/clear
You: How does it differ from Go?       <- agent has no context, will ask for clarification
```

**RU example:**
```
You: Расскажи о Python в двух предложениях
You: А чем он отличается от Go?
```

## Day 7 — Persistent Memory

FileMemory stores chat history in `data/history_{user}.json`. The dialog survives restarts:
- Atomic writes (tempfile + rename) prevent corruption.
- Validation: if the last message is `role == "user"` (orphaned after crash), it's dropped on load.
- JSON format: `ensure_ascii=False, indent=2` for readability and non-ASCII support.
- `/clear` empties chat history (both RAM and file); session token stats are not affected.

`Agent` depends on `Memory` Protocol (duck typing). This allows swapping `SessionMemory` for `FileMemory` without changing `Agent`.

### Demo (for the video)

**Show persistence:**
```bash
uv run python -m week_02.main --user=john
You: Tell me about Python
# Get an answer
exit

uv run python -m week_02.main --user=john
You: What did I ask you before?
# Agent remembers the previous question
```

**Show multi-user:**
```bash
uv run python -m week_02.main --user=alice
You: I prefer Rust
exit

uv run python -m week_02.main --user=john
You: What language do I like?
# John's history is separate from Alice's
```

**Show /clear:**
```bash
/clear
# Check the file:
cat data/history_john.json
# File contains []
```

## Day 8 — Token Accounting & Context Overflow

After each model response, a dim status line shows token usage and cost:

```
Tokens: 312 prompt + 47 completion = 359 | Cost: $0.000135 | Session: 731 tokens ($0.000274)
```

When the accumulated context exceeds the `SlidingWindowPolicy(max_tokens=500)` budget
(demo knob), the oldest messages are dropped one by one from the slice sent to the API
(and a leading `assistant` message is also dropped, so the trimmed context still starts
with a `user` turn):

```
[yellow]Context limit reached. Dropped 4 old messages — the model no longer sees them.[/]
```

**Key design points:**
- Token cost is calculated via `shared/pricing.py` using `PRICING` from `shared/config.py`.
- `TokenStats` (in `week_02/stats.py`) tracks session totals in RAM; preserved on `/clear`
  and `/switch` — spent tokens are not undone by clearing history.
- `max_tokens=500` (in `SlidingWindowPolicy`) and the `1 token ≈ 4 chars` heuristic are
  **demo settings**, not a real tokenizer. Note: `4 chars/token` is English-calibrated;
  Cyrillic is ~3 chars/token, so the actual API token count at the drop threshold is higher.
- Only the slice sent to the API is trimmed. The `data/history_{user}.json` file from Day 7
  remains complete — nothing is lost from disk.
- Demo is honest: trimming is done by the app, not the provider. Some gateways (e.g. OpenRouter)
  silently auto-trim, which hides what actually breaks at overflow.
- **Why overflow matters:** when early messages leave the context window, the model doesn't
  know it lost them — it fills the gap with plausible fabrication. This is a primary source
  of hallucinations.

### Demo

**Show token growth:**
```bash
uv run python -m week_02.main --user=demo
You: My favourite language is Python
# dim line: Session: ~80 tokens
You: Tell me about it in detail
# dim line: Session grows
You: What are its main use cases?
# Session totals keep rising with each turn
```

**Show context overflow and forgetting:**
```bash
# Keep sending long messages until:
# [yellow]Context limit reached. Dropped N old messages — the model no longer sees them.[/]

You: What is my favourite language?
# Model no longer has the first message → guesses or admits it doesn't know
```

**Show history file is untouched:**
```bash
# In another terminal:
cat data/history_demo.json
# Full history still there — only the API slice was trimmed
```

**Show /clear resets history but not stats:**
```bash
/clear
# History is gone — but dim line still shows accumulated session tokens/cost
# Stats survive because the money was already spent
```

## Day 9 — Context Compression via Summary

Two pluggable policies via `--policy`:

- `sliding` (default): Day 8 truncation — oldest messages dropped when context exceeds limit.
- `summary`: last N messages kept raw; older messages folded into an LLM-generated summary stored in `data/summary_{user}.json`. `build_messages` injects the summary as a system turn, then appends all uncompressed messages.

Summary is incremental: only newly-old messages are sent to the summarizer. Raw history file remains complete.
The summarizer uses a merge-aware prompt: first compression summarizes from scratch;
subsequent compressions merge the previous summary with new messages, explicitly
instructing the model to carry all earlier facts forward. Retention quality depends
on the summarizer model (DeepSeek R1 preserves facts across 2+ compressions; GPT-4o
may drop them on long chunks — an honest lossy trade-off).

Summary state format:
```json
{"summary": "• Fact A\n• User prefers X", "compressed_up_to": 12}
```

Summary model is fixed to the provider chosen at startup and does not change on `/switch`.
Summary usage is attributed via `CompressionResult.usage_model_id` to the summary model (not the
current chat model) for accurate session cost even after `/switch`.
`/clear` resets both memory and summary state; session stats are preserved.

Demo steps:
```bash
uv run python -m week_02.main --user=demo --policy=sliding
# 15+ messages → overflow + forgetting (Day 8 behaviour)

uv run python -m week_02.main --user=demo2 --policy=summary
# same dialogue → summary kicks in, early facts retained via summary
cat data/summary_demo2.json
```

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 6 | First Agent (streaming CLI, SessionMemory) | `/clear`, `/switch`, `/help` | `agent.py`, `memory.py`, `cli.py` | done | _link_ |
| 7 | Persistent Memory (FileMemory, Protocol, argparse) | `--user` | `memory.py` (FileMemory, Protocol), `main.py` (argparse) | done | _link_ |
| 8 | Token accounting + context overflow demo | auto stats line | `context.py` (`SlidingWindowPolicy`), `stats.py`, `shared/pricing.py`, `cli.py` | done | _link_ |
| 9 | Context compression (sliding vs summary policies) | `--policy` | `context.py`, `summarizer.py`, `agent.py`, `cli.py`, `main.py` | done | _link_ |

All days share one codebase; the table maps each day to its commands and the modules that implement them.
