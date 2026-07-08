# Week 06 — Local LLM Launch

## Structure

```text
week_06/
├── main.py          # entrypoint: interactive ask loop, or one-shot with --prompt
├── local_client.py  # thin Day 26 wrapper over shared/client.py
└── README.md        # commands, manual prompts, demo flow, progress
```

No `__init__.py` in `week_06/` (PEP 420 namespace package), same run style as earlier weeks:
`uv run python -m week_06.main`.

## Base Setup

```bash
uv sync
```

Install Ollama on Windows, start it, and pull a local coder model:

```bash
ollama pull qwen2.5-coder:7b
# fallback for weaker machines:
ollama pull qwen2.5-coder:3b
```

## Local Provider Setup

Ollama exposes an OpenAI-compatible local endpoint:

```text
http://localhost:11434/v1
```

`week_06` does not create a separate raw HTTP client. Local Ollama models are registered in
`shared/config.py` as keyless providers:

```text
Qwen2.5 Coder 7B (Ollama, local) -> qwen2.5-coder:7b
Qwen2.5 Coder 3B (Ollama, local) -> qwen2.5-coder:3b
```

`shared/client.py` handles them through the same OpenAI SDK path used by cloud providers. Cloud providers still require API keys; local providers use `api_key_env=None` in config.

## Day 26 — Local LLM Launch

### Goal

Launch any local LLM and prove it works:

- model runs locally,
- it is reachable through CLI or HTTP API,
- it answers a simple request,
- at least 3 prompts of different complexity are demonstrated.

Day 26 does not require RAG, MCP, memory, or an agent. This is a local inference proof.

### Manual Prompts

Three prompts run by hand in the demo (one at a time). They live in the README, not in code —
Day 26 is about live interaction with the model, not batch automation. Prompt bodies are kept in
Russian on purpose; technical terms stay in English.

How complexity is graded:

- **simple** — single operation, little context, strict short format (JSON classification);
- **medium** — generate code + test and hold the output format (Flask + pytest);
- **complex** — many constraints at once: state machine, idempotency, retries, cleanup,
  CloudWatch, IAM/Secrets — the model must keep all of it in one answer.

#### Prompt 1 — simple / OneDrive classification

```text
Классифицируй обращение как bug, question или feature_request.
Текст: "После обновления Windows 11 OneDrive перестал синхронизировать папку проекта. Файлы видны локально, но не появляются в облаке."
Ответь только JSON: {"type":"...","reason":"..."}
```

#### Prompt 2 — medium / Flask + pytest

```text
Напиши минимальный Flask endpoint GET /healthz, который возвращает JSON {"status":"ok","service":"cloud-studio"} и HTTP 200.
Добавь pytest-тест для этого endpoint.
Ответ дай двумя блоками: app.py и test_app.py.
Без лишних комментариев.
```

#### Prompt 3 — complex / AWS lifecycle architecture

```text
Мы строим cloud-based development and validation studio на AWS.
Опиши lifecycle flow для on-demand compute environment:
create -> ready -> active -> stop -> cleanup.

Ответ дай в Markdown:
1. state machine;
2. где нужны idempotency keys;
3. где нужны retries/backoff;
4. как чистить zombie resources;
5. минимальные CloudWatch metrics;
6. базовые IAM и Secrets Manager guardrails.

Ограничения:
- backend: Python, Flask, SQLAlchemy, boto3;
- без кода;
- коротко;
- добавь таблицу risk -> mitigation максимум на 3 строки.
```

## Run (bash)

What each command does:

```bash
# check Ollama is installed
ollama --version

# list models pulled locally
ollama list

# direct CLI run through Ollama itself (proves the model is local)
ollama run qwen2.5-coder:7b "Коротко объясни, что такое локальная LLM"

# proves the OpenAI-compatible HTTP API is up (this is what shared/client.py calls)
curl http://localhost:11434/v1/models
```

### Interactive (ask) mode — main path

Start without `--prompt` and type requests live; the model answers in a loop. `exit`/`quit`/empty
line exits. This is how the 3 prompts are run in the demo.

```bash
# default provider (7B)
uv run python -m week_06.main

# lighter, if memory is tight (3B)
uv run python -m week_06.main --provider "Qwen2.5 Coder 3B (Ollama, local)"
```

```text
ask> <paste Prompt 1 from README>
ask> <paste Prompt 2>
ask> <paste Prompt 3>
ask> exit
```

### One-shot mode — for scripts / a single request

When you need a single answer without the loop (prompt passed as an argument):

```bash
uv run python -m week_06.main --prompt "Коротко объясни, что такое локальная LLM"
```

## What To Verify

- `ollama list` contains `qwen2.5-coder:7b` or `qwen2.5-coder:3b`.
- `ollama run ...` returns an answer locally.
- `curl http://localhost:11434/v1/models` returns local model metadata.
- `uv run python -m week_06.main` opens the `ask>` loop and answers each typed prompt.
- each answer prints: provider, model id, latency, finish_reason, answer text.
- the three prompts show rising complexity: classification -> code -> architecture.

## Example Output

```text
Day 26 local LLM demo
provider=Qwen2.5 Coder 7B (Ollama, local) model=qwen2.5-coder:7b

Interactive ask mode. Type a prompt, empty line or 'exit'/'quit' to stop.

ask> Коротко объясни, что такое локальная LLM
latency_s=1.82 finish_reason=stop
Локальная LLM — это языковая модель, которая работает на твоём устройстве или сервере...

ask> exit
```

### Done

- Local Ollama providers added to `shared/config.py`.
- Local providers are keyless (`api_key_env=None`) and reuse `shared/client.py`.
- `week_06/local_client.py` is only a thin Day 26 wrapper around shared transport.
- `week_06/main.py` has an interactive ask loop (default) and one-shot `--prompt` mode.
- README contains 3 manual prompts of different complexity for the video.

### Not Done

- No RAG integration with the local model yet.
- No local-vs-cloud comparison yet.
- No persistent history between turns; the ask loop is stateless per prompt (Day 26 scope).

## Troubleshooting (bash + Ollama)

- `model not found`:
  - run `ollama pull qwen2.5-coder:7b`.
- `Connection refused` / API connection error:
  - start Ollama app or run `ollama serve`.
- Too slow / high memory:
  - use `--provider "Qwen2.5 Coder 3B (Ollama, local)"`.
- Python import error:
  - run from repo root with `uv run python -m week_06.main`.

## Demo Flow (short)

1. Show `ollama --version`.
2. Show `ollama list` with local Qwen model.
3. Show CLI call through `ollama run ...`.
4. Show HTTP proof through `curl http://localhost:11434/v1/models`.
5. Start the ask loop: `uv run python -m week_06.main`.
6. Paste Prompt 1 (simple), then Prompt 2 (medium), then Prompt 3 (complex).
7. Show latency/finish_reason for each response.
8. Type `exit` to close the loop.

---

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 26 | Launch local LLM through Ollama, prove CLI/API access, run 3 manual prompts of different complexity | `ollama run qwen2.5-coder:7b`, `curl /v1/models`, `-m week_06.main --prompt "..."` | `main.py`, `local_client.py`, `shared/config.py`, `shared/client.py`, `README.md` | done | _link_ |
