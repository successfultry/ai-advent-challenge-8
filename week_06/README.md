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

`shared/client.py` handles them through the same OpenAI SDK path used by cloud providers. Cloud
providers still require API keys; local providers use `api_key_env=None` in config.

## Day 26 — Local LLM Launch

### Goal

Launch any local LLM and prove it works:

- model runs locally,
- it is reachable through CLI or HTTP API,
- it answers a simple request,
- at least 3 prompts of different complexity are demonstrated.

Day 26 does not require RAG, MCP, memory, or an agent. This is a local inference proof.

### Manual Prompts

Три промпта, которые я прогоняю в демо руками (по одному). Они специально лежат в README, а не в
коде — Day 26 про живое взаимодействие с моделью, а не про автопрогон.

Как определяется сложность:

- **simple** — одна операция, мало контекста, строгий короткий формат (классификация в JSON);
- **medium** — надо сгенерировать код + тест + выдержать формат вывода (Flask + pytest);
- **complex** — много ограничений сразу: state machine, idempotency, retries, cleanup,
  CloudWatch, IAM/Secrets — модель должна держать всё это в одном ответе.

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
Нужно описать lifecycle flow для on-demand compute environment:
create -> ready -> active -> stop -> cleanup.

Сделай архитектурную записку:
1. state machine и допустимые transitions;
2. где нужны idempotency keys;
3. где нужны retries/backoff;
4. как чистить zombie resources;
5. какие CloudWatch metrics и alerts нужны минимально;
6. какие IAM и Secrets Manager guardrails включить по умолчанию.

Ограничения:
- backend: Python, Flask, SQLAlchemy, boto3;
- без overengineering;
- ответ в Markdown с короткой таблицей risk -> mitigation.
```

## Run (bash)

Что делает каждая команда:

```bash
# проверить, что Ollama установлена
ollama --version

# посмотреть, какие модели скачаны локально
ollama list

# прямой прогон через CLI самой Ollama (доказательство, что модель локальная)
ollama run qwen2.5-coder:7b "Коротко объясни, что такое локальная LLM"

# доказательство, что живёт OpenAI-совместимый HTTP API (его и дёргает shared/client.py)
curl http://localhost:11434/v1/models
```

### Интерактивный (ask) режим — основной способ

Запускаешь без `--prompt` и вводишь запросы вживую, модель отвечает в цикле. `exit`/`quit`/пустая
строка — выход. Именно так гоняются 3 промпта в демо.

```bash
# дефолтный провайдер (7B)
uv run python -m week_06.main

# послабее, если тяжело по памяти (3B)
uv run python -m week_06.main --provider "Qwen2.5 Coder 3B (Ollama, local)"
```

```text
ask> <вставляешь Prompt 1 из README>
ask> <вставляешь Prompt 2>
ask> <вставляешь Prompt 3>
ask> exit
```

### One-shot режим — для скрипта/одиночного запроса

Когда нужен один ответ без цикла (передаёшь prompt аргументом):

```bash
uv run python -m week_06.main --prompt "Коротко объясни, что такое локальная LLM"
```

## What To Verify

- `ollama list` contains `qwen2.5-coder:7b` or `qwen2.5-coder:3b`.
- `ollama run ...` returns an answer locally.
- `curl http://localhost:11434/v1/models` returns local model metadata.
- `uv run python -m week_06.main` opens the `ask>` loop and answers each typed prompt.
- каждый ответ печатает: provider, model id, latency, finish_reason, текст ответа.
- три промпта показывают рост сложности: classification -> code -> architecture.

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
