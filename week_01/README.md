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
uv run python week_01/main.py
```

Make sure `.env` exists in the repo root with at least one key:

```
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...
```

## Progress

| Day | Task | What it does | Video |
|-----|------|--------------|-------|
| 1 | First LLM request via API | Interactive CLI: pick provider (DeepSeek/OpenAI) → type question → get streaming response. Chat history kept in session, API errors handled gracefully. | _link_ |
