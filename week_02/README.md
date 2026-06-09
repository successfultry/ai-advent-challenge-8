# Week 02 — Agent internals: context, memory, planning, tools

## Structure

```
week_02/
├── main.py      # entrypoint
├── cli.py       # terminal UI (rich, chat loop)
├── agent.py     # Agent — orchestrator: SessionMemory + LLM client
└── memory.py    # SessionMemory — stores conversation history
```

Providers and HTTP client live in `shared/` (imported from `shared.client` and `shared.config`).

## Run

```bash
uv run python -m week_02.main
```

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

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 6 | First Agent (streaming CLI, SessionMemory) | `/clear`, `/switch`, `/help` | `agent.py`, `memory.py`, `cli.py` | done | _link_ |

All days share one codebase; the table maps each day to its commands and the modules that implement them.
