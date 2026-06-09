# AI Advent Challenge #8

Personal submissions repo. Python 3.12 + [uv](https://docs.astral.sh/uv/).

## Layout

```
shared/
  config.py      ← providers, models, pricing
  client.py      ← HTTP client, streaming, API calls
  cli_helpers.py ← shared UI helpers (pick_provider)
week_XX/
  main.py        ← entrypoint
  cli.py         ← terminal UI
  README.md      ← week description + daily progress
```

## Run

```bash
uv sync                        # install deps
uv run python -m week_01.main  # week 1 — LLM playground
uv run python -m week_02.main  # week 2 — agent chat
```

## Progress

| Week | Theme | Status |
|------|-------|--------|
| 1 | Basics of LLMs & prompting | done |
| 2 | Agent internals: context, memory, planning, tools | in progress |
