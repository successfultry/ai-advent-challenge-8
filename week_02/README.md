# Week 02 — Agent internals: context, memory, planning, tools

## Structure

```
week_02/
├── main.py        # entrypoint (argparse --user, --policy)
├── cli.py         # terminal UI (rich, chat loop)
├── agent.py       # Agent — orchestrator: Memory + Policy + LLM
├── memory.py      # Memory (Protocol), FileMemory, BranchingMemory
├── context.py     # ContextPolicy (Protocol), SlidingWindow, Summary, Facts
├── facts.py       # LLM-based key-value fact extraction
├── stats.py       # TokenStats (session totals)
└── summarizer.py  # LLM-based summary generation
```

`Memory` is a `typing.Protocol` defining the interface (`add`, `history`, `pop_last`, `clear`).
`FileMemory` stores history in `data/history_{user}.json` (persistent).
`BranchingMemory` wraps per-branch `FileMemory` instances (Day 10).

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
- in-memory history update after each turn.

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

`Agent` depends on `Memory` Protocol (duck typing). This allows swapping any `Memory` implementation (`FileMemory`, `BranchingMemory`) without changing `Agent`.

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

## Day 10 — Facts strategy, runtime switching, branching

### Facts context strategy (`--policy=facts`)

`FactsPolicy` maintains a persistent key-value store extracted from conversation history
by an auxiliary LLM call after each informative user message.

```bash
uv run python -m week_02.main --user=demo --policy=facts
```

- Facts are stored in `data/facts_<user>.json` and survive restarts.
- `build_messages` injects a `Known facts:` system block. If no facts yet, full history
  is returned (coverage invariant — nothing is dropped before it is captured).
- **Cost skip-guard:** extraction is skipped for trivially non-informative messages
  (< 12 chars or stop-list: `ok/ок/да/нет/спасибо/next/go/...`). Informative turns
  always trigger it. `FactsResult.facts_count` carries no `dropped` field — facts is
  extraction, not compression.

### Runtime policy switching (`/policy`)

Swap the context strategy mid-session without losing history:

```
/policy sliding     # sliding window (no auxiliary LLM calls)
/policy summary     # summarization
/policy facts       # facts extraction
/policy branching   # full history, no processing (use with /branch)
```

Memory and token stats are preserved across switches. The new policy starts with
empty own state and begins accumulating from the next turn.

### Conversation branching (`/branch`)

`BranchingMemory` is always the active memory type. A fresh session starts on the
`main` branch (backed by the existing `data/history_<user>.json` — fully backward
compatible). Branch metadata is stored in `data/branches_<user>.json`.

```
/branch new <name>      # fork current branch into a new one, switch to it
/branch switch <name>   # switch to an existing branch
/branch list            # list all branches with active marker
```

Branches are per-user file-isolated (`data/history_<user>__<name>.json`). Context
policies stay branch-agnostic — they only call `memory.history()` and are unaware of
the branch structure. Facts/summary state is also per-branch (`facts_<user>__<branch>.json`);
a forked branch starts with empty derived state and recomputes it from the copied history.

Branching (memory axis) and policy (context axis) are orthogonal: a branch always runs
under some policy (sliding by default). All combinations are valid — e.g. `facts` on a
forked branch, `sliding` on `main`.

`--policy=branching` selects `NonePolicy` (full history, zero processing) so branching
can be used as a standalone context strategy with no sliding trim and no auxiliary LLM
calls. It does **not** disable branching under other policies — `/branch` works under any
policy (e.g. `facts` + branches in demo 3 below).

### Demo (for the video)

Clean up before recording (fresh users):
```bash
del data\history_d10a.json data\facts_d10a.json data\branches_d10a.json 2>$null
del data\history_d10b.json data\facts_d10b.json data\branches_d10b.json 2>$null
del data\history_d10c.json data\facts_d10c.json data\branches_d10c.json 2>$null
del data\history_d10c__experiment.json data\facts_d10c__experiment.json 2>$null
```

**1. Facts extraction + cost skip-guard:**

```bash
uv run python -m week_02.main --user=d10a --policy=facts
```

| You type | Expected output | Why |
|----------|----------------|-----|
| `Меня зовут Иван, мне 30 лет, я программист из Мордовии` | dim: `Facts updated (N facts)` | Informative message → facts extracted |
| `ок` | **No** `Facts updated` line | Skip-guard: < 12 chars |
| `да` | **No** `Facts updated` line | Skip-guard: word in stop-list |
| `Я работаю на Python и Go, предпочитаю Linux` | dim: `Facts updated (N facts)` — N grows | New info → facts appended |
| `Что ты обо мне знаешь?` | Model lists: Иван, 30, Мордовия, Python/Go, Linux | Answer built from facts block |
| `exit` | | |

Verify persisted facts:
```bash
cat data/facts_d10a.json
# → {"name": "Иван", "age": "30", "profession": "программист", ...}
```

**2. Runtime policy switch (history preserved):**

```bash
uv run python -m week_02.main --user=d10b --policy=facts
```

| You type | Expected output |
|----------|----------------|
| `Меня зовут Алексей, я дизайнер из Питера` | dim: `Facts updated (N facts)` |
| `/policy sliding` | dim: `Policy switched to sliding.` |
| `Что ты знаешь обо мне?` | Model answers — Алексей, Питер (still in sliding window) |
| `/policy facts` | dim: `Policy switched to facts.` |
| `Что ты знаешь обо мне?` | Model answers — Алексей, дизайнер, Питер (facts reloaded from disk) |
| `exit` | | |

**3. Branching with branch-scoped facts:**

```bash
uv run python -m week_02.main --user=d10c --policy=facts
```

| You type | Expected output |
|----------|----------------|
| `Меня зовут Дмитрий, я из Казани` | dim: `Facts updated (N facts)` |
| `/branch list` | `main ← active` |
| `/branch new experiment` | dim: `Created and switched to branch experiment.` |
| `Забудь всё. Теперь меня зовут Сергей и я из Новосибирска` | dim: `Facts updated` (experiment branch facts) |
| `/branch switch main` | dim: `Switched to branch main.` |
| `Как меня зовут и откуда я?` | → **Дмитрий, Казань** (main facts) |
| `/branch switch experiment` | dim: `Switched to branch experiment.` |
| `Как меня зовут и откуда я?` | → **Сергей, Новосибирск** (experiment facts) |
| `/branch list` | `main`, `experiment ← active` |
| `exit` | |

Verify branch isolation:
```bash
cat data/facts_d10c.json
# → Дмитрий / Казань (main branch)

cat data/facts_d10c__experiment.json
# → Сергей / Новосибирск (experiment branch)

cat data/branches_d10c.json
# → {"active": "experiment", "branches": ["main", "experiment"]}
```

### Strategy comparison (the task deliverable)

Same scenario — collecting a short spec (ТЗ) in 10 messages — run on each strategy.
Copy-paste the messages below into each session, then check message 10 (the recall question).

**Scenario messages (same for all three):**
```
1: Давай соберём ТЗ на телеграм-бота для заметок
2: Цель: пользователь шлёт текст, бот сохраняет и умеет искать по тегам
3: Ограничение: только Python, хостинг — бесплатный tier
4: Предпочтение: минимум зависимостей, без тяжёлых фреймворков
5: Договорились: хранилище — SQLite
6: Добавь: бот должен поддерживать напоминания по времени
7: Ещё: экспорт заметок в Markdown
8: Уточнение: теги вводятся через #hashtag в тексте
9: Решение: поиск делаем по подстроке + по тегам
10: Напомни всё: какая цель, стек, ограничения и все решения?
```

**Run 1 — Sliding Window:**
```bash
uv run python -m week_02.main --user=cmp_slide --policy=sliding
```
Enter messages 1-10. By message 10 the sliding window (`max_tokens=500`) has dropped
early messages → model partially forgets goal/constraints.

**Run 2 — Sticky Facts:**
```bash
uv run python -m week_02.main --user=cmp_facts --policy=facts
```
Same 10 messages. Each informative turn shows `Facts updated`. On message 10 the model
answers from the facts block → full recall expected.

**Run 3 — Branching:**
```bash
uv run python -m week_02.main --user=cmp_branch --policy=branching
```
Messages 1-5 (base spec), then fork:
```
/branch new variant_a
```
Messages 6-7 as above (напоминания + экспорт). Then:
```
/branch switch main
/branch new variant_b
```
Alternative messages 6-7:
```
Добавь: бот должен поддерживать голосовые заметки через Whisper
Ещё: интеграция с Google Calendar
```
Then verify branch isolation:
```
/branch switch variant_a
Напомни всё ТЗ
# → цель, SQLite, теги, напоминания, экспорт

/branch switch variant_b
Напомни всё ТЗ
# → цель, SQLite, теги, голосовые заметки, Google Calendar
```

**Results** (measured on the 10-message ТЗ scenario, DeepSeek V3):

| Criterion | Sliding | Facts | Branching |
|-----------|---------|-------|-----------|
| Recalls goal/stack/constraints? | Partial — lost "Python-only / free hosting / min deps" | Full | Full (per branch) |
| Hallucinations? | Yes — invented "no Docker / apscheduler / asyncio" for the dropped constraints | None | None |
| Extra LLM calls per turn | 0 | 1 (facts extraction) | 0 |
| Session tokens / cost | ~3.9k / $0.0026 (cheapest, lossy) | ~33.9k / $0.0127 (priciest, reliable) | ~24k / $0.010 (mid) |
| Scales to long conversations? | Window fixed → forgets | Facts compact → scales | Branches grow unbounded, but stay short |
| Best for | throwaway chats | long linear spec where everything matters | exploring alternative variants |

**Outcome:** `sliding` doesn't just forget — once early messages fall out of the window
the model **confidently fabricates** replacements (it invented "no Docker", "apscheduler",
"asyncio" — none were ever said). This is a primary source of hallucination. `facts` fixes
it with full recall at ~5× the token cost. `branching` solves a different problem: `variant_a`
(reminders + Markdown export) and `variant_b` (voice via Whisper + Google Calendar) diverged
from a shared checkpoint and each recalled its own spec with zero cross-contamination.

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 6 | First Agent (streaming CLI, in-memory history) | `/clear`, `/switch`, `/help` | `agent.py`, `memory.py`, `cli.py` | done | _link_ |
| 7 | Persistent Memory (FileMemory, Protocol, argparse) | `--user` | `memory.py` (FileMemory, Protocol), `main.py` (argparse) | done | _link_ |
| 8 | Token accounting + context overflow demo | auto stats line | `context.py` (`SlidingWindowPolicy`), `stats.py`, `shared/pricing.py`, `cli.py` | done | _link_ |
| 9 | Context compression (sliding vs summary policies) | `--policy` | `context.py`, `summarizer.py`, `agent.py`, `cli.py`, `main.py` | done | _link_ |
| 10 | 3 context strategies (sliding / facts / branching) + runtime switching + comparison | `--policy`, `/policy`, `/branch` | `context.py` (`NonePolicy`, `FactsPolicy`), `facts.py`, `memory.py` (`BranchingMemory`), `cli.py` | done | _link_ |

All days share one codebase; the table maps each day to its commands and the modules that implement them.
