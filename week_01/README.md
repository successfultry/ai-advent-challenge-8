# Week 01 — Basics of LLMs & prompting

## Structure

```
week_01/
├── main.py      # entrypoint
├── cli.py       # terminal UI (rich, меню, chat loop)
├── client.py    # API logic (create client, streaming)
├── config.py    # provider registry (urls, models, env vars)
└── README.md
```

## Run

```bash
uv run python -m week_01.main
```

Make sure `.env` exists in the repo root with at least one key:

```
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...
```

## Day 1 — First LLM request via API

Interactive terminal chat that talks to a real LLM over its HTTP API (no aggregator).

Flow:

1. Pick a provider from the menu (only models with a present API key are shown).
2. Type a question (RU/EN) → the answer streams back token by token.
3. After each answer the prompt/completion token usage is printed.

In-chat commands:

| Command | Action |
|---------|--------|
| `/switch` | back to the model menu (switch provider) |
| `/clear` | clear chat history for the current session |
| `/help` | list commands |
| `exit` / `quit` / `выход` | quit |

Chat history is kept per session; API/network errors are caught and shown as a
message instead of crashing.

## Progress

| Day | Task | Status | Video |
|-----|------|--------|-------|
| 1 | First LLM request via API (streaming CLI) | done | _link_ |
