# Week 06 — Local LLM Launch

## Structure

```text
week_06/
├── main.py                   # Day 26 interactive ask loop / one-shot mode
├── local_client.py           # thin local Ollama wrapper over shared/client.py
├── workbench.py              # Day 27 use-case layer (modes + history + ask)
├── web_app.py                # Day 27 Flask transport layer
├── local_rag.py              # Day 28 RAG: local lexical retrieval, local vs cloud generation
├── templates/
│   └── workbench.html        # Day 27 UI
├── static/
│   └── favicon.ico           # web app tab icon
└── README.md                 # commands, prompts, app runbook, progress
```

No `__init__.py` in `week_06/` (PEP 420 namespace package), same run style as earlier weeks:
`uv run python -m week_06.main`.

## Base Setup

```bash
uv sync
```

Install Ollama on Windows, start it, and pull the local models used this week:

```bash
ollama pull qwen2.5:3b
ollama pull qwen2.5-coder:3b
# optional on stronger local machines; not used for the CPU-only VPS demo:
ollama pull qwen2.5-coder:7b
```

## Local Provider Setup

Ollama exposes an OpenAI-compatible local endpoint:

```text
http://localhost:11434/v1
```

`week_06` does not create a separate raw HTTP client. Local Ollama models are registered in
`shared/config.py` as keyless providers:

```text
Qwen2.5 3B (Ollama, local)       -> qwen2.5:3b
Qwen2.5 Coder 3B (Ollama, local) -> qwen2.5-coder:3b
Qwen2.5 Coder 7B (Ollama, local) -> qwen2.5-coder:7b
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

## Day 27 — Integrate Local LLM in an App

### Goal

Ship a real local app that uses the local Ollama model:

- app sends requests to local LLM;
- app receives and displays answers;
- app works without cloud models.

### Architecture

The implementation is intentionally split so Day 27 stays simple now, but can be extended later:

- **UI / transport layer**: Flask app (`week_06/web_app.py`) and HTML UI (`week_06/templates/workbench.html`);
- **Use-case layer**: prompt modes, prompt building, request handling, in-memory history (`week_06/workbench.py`);
- **LLM layer**: existing local provider wrapper (`week_06/local_client.py`) backed by `shared/client.py`;
- **Future retrieval layer**: not implemented now (reserved for RAG / TG-export search later).

### Run Day 27 App

```bash
# once (already done if flask is installed)
uv add flask

# start local web app
uv run python -m week_06.web_app
```

Open:

```text
http://127.0.0.1:8000
```

### Modes

The app provides 4 modes:

- `general`
- `explain_error`
- `generate_pytest`
- `architecture_review`

Each mode prepends a small system instruction, then sends the final prompt to the local model.

### Day 27 Sample Inputs

```text
Mode: general
Объясни, что такое локальная LLM, в 3 коротких пунктах.
```

```text
Mode: explain_error
sqlalchemy.exc.OperationalError: connection refused on localhost:5432
Ответь в 3 пунктах: причина, проверка, фикс.
```

```text
Mode: generate_pytest
from flask import Flask, jsonify

app = Flask(__name__)

@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": "cloud-studio"}), 200
```

### What To Verify (Day 27)

- the page opens on `http://127.0.0.1:8000`;
- **Check local model** returns healthy status;
- mode switch changes behavior (error explanation vs tests vs architecture review);
- response includes `latency_s`, `finish_reason`, and model id;
- history shows the last 5 requests and can refill prompt/mode.

### Demo Flow (Day 27)

1. Start app: `uv run python -m week_06.web_app`.
2. Open `http://127.0.0.1:8000`.
3. Click **Check local model**.
4. Run `explain_error` with a terminal stack trace.
5. Run `generate_pytest` with a small Flask endpoint snippet.
6. Run `architecture_review` with a short AWS lifecycle prompt.
7. Show response metadata and history refill.

## Day 28 — Local LLM + Local RAG (Week 5 index reuse)

### Goal

Reuse the existing Week 5 SQLite index for RAG where **retrieval is local lexical** and only the
**generator** changes:

- **Local (required flow):** lexical retrieval + local Ollama generation. Fully offline, no network.
- **Cloud (comparison):** the **same** lexical context + cloud generation (DeepSeek/GPT).

Keeping retrieval identical means the comparison isolates a single variable — the generator — so
`compare`/`eval` show honestly what you gain/lose by going local. Both report **symmetric metrics**
(retrieval latency, generation latency, total latency, keyword recall, source hit) side by side.

### Why local lexical retrieval (the embedding-space point)

Week 5 stored chunk vectors with `text-embedding-3-small` (OpenAI, 1536 dims). For vector search
the **query** must be embedded by the **same model into the same space**:

- a local embedder gives either a different dimensionality (cosine breaks) or the same
  dimensionality in a different space (cosine ranks are meaningless);
- re-embedding locally would mean rebuilding the whole index.

So local retrieval is **lexical (TF-IDF over `chunks.text`)** — no vectors, fully local, nothing to
download. The stored cloud vectors are intentionally ignored in the default flow.

### Optional: cloud vector retrieval (`--cloud-retrieval vector`)

The stored OpenAI vectors *are* usable if the query is embedded by the **same** OpenAI model. As an
optional experiment, `compare`/`eval` accept `--cloud-retrieval vector`: the cloud side then embeds
the query via OpenAI `text-embedding-3-small` and does cosine over the stored `embedding_json`
(needs `OPENAI_API_KEY`). This makes it a full local-stack vs cloud-stack comparison, but it changes
two variables at once (retrieval + generation), so the default stays `lexical`.

### Runtime Architecture (Day 28)

```text
retrieval (shared): week_05 SQLite (chunks.text) -> lexical TF-IDF retrieval -> ranked chunks

LOCAL  : ranked chunks -> grounded prompt -> local Ollama generation (qwen2.5-coder:7b)   [offline]
CLOUD  : ranked chunks -> grounded prompt -> cloud generation (DeepSeek/GPT)              [gen key]

optional (--cloud-retrieval vector):
CLOUD  : query -> OpenAI text-embedding-3-small -> cosine vs stored embedding_json -> chunks
         -> grounded prompt -> cloud generation                                  [OPENAI_API_KEY]
```

What is reused from the Week 5 index:

- `index_runs` metadata (pick latest run; read the indexed embedding model);
- `chunks.text` + metadata → lexical retrieval (both pipelines by default);
- `chunks.embedding_json` (old cloud vectors) → only in optional `--cloud-retrieval vector`.

Cloud requirements:

- default (lexical): a cloud generation key (e.g. `DEEPSEEK_API_KEY`) — no OpenAI needed;
- `--cloud-retrieval vector`: additionally `OPENAI_API_KEY` (to embed the query in the indexed
  space).

If the needed keys are missing, the cloud side is skipped with a clear reason and the local flow
still fully satisfies Day 28.

### Run Day 28

```bash
# local pipeline: lexical retrieval + local generation
uv run python -m week_06.local_rag ask --question "Из каких шагов состоит базовый pipeline RAG?"

# compare local vs cloud generation on the SAME lexical context (default)
uv run python -m week_06.local_rag compare --question "Что такое cosine similarity?"

# optional: full cloud stack (cloud vector retrieval + cloud generation)
uv run python -m week_06.local_rag compare --question "Что такое cosine similarity?" --cloud-retrieval vector

# mini evaluation with symmetric local/cloud metrics (quality/speed/stability)
uv run python -m week_06.local_rag eval --limit 2
```

Interactive ask mode:

```bash
uv run python -m week_06.local_rag ask
```

### What To Verify (Day 28)

- Day 28 prints reused `run_id`, `strategy`, and the indexed `embedding_model` from Week 5 DB;
- local pipeline: lexical retrieved chunks (`source`, `section`, `chunk_id`, score) + local
  Ollama answer, generated with no network;
- cloud pipeline (if a generation key is present): the **same** lexical context + cloud answer;
  `compare` prints both under `== LOCAL ==` / `== CLOUD ==` headers, with identical
  `retrieval_latency_s` (retrieval is shared);
- `eval` writes JSON report to `week_06/eval/day28_results.json` with **symmetric** `local` and
  `cloud` metric blocks (per-question and aggregated), plus `cloud_retrieval_mode`;
- if no cloud generation key is set, the cloud side is skipped and the local flow still succeeds.

### Demo Flow (Day 28)

1. Show that local model is available (`ollama list`).
2. Run `uv run python -m week_06.local_rag ask --question "..."` — lexical retrieval + local answer.
3. Show retrieved chunks + local answer + latencies (retrieval ~0.03s, generation dominates).
4. Run `compare` once: `== LOCAL ==` (Qwen) vs `== CLOUD ==` (DeepSeek) on the **same** lexical
   context. Point out `retrieval_latency_s` is identical — only the generator changed.
5. Run `eval --limit 3` and show the two symmetric summaries (`[LOCAL]` vs `[CLOUD]`) + report path:
   local is private/offline but slow on CPU; cloud is far faster, quality is close.
6. (Optional) Re-run `compare ... --cloud-retrieval vector` to show the full cloud stack reusing the
   old OpenAI vectors.

## Day 29 — Optimize Local LLM (Path A)

### Goal

Optimize the local generation step of the same RAG Q&A flow (Week 5 lexical retrieval + local
Qwen2.5-Coder-7B) for a concrete use case (Russian technical course notes), then compare
**before vs after** on quality, speed, and format stability.

### What the `optimize` command analyzes

It runs the **same** dataset question twice per row, on the **same** Ollama model
(`qwen2.5-coder:7b`, Q4_K_M) with **identical lexical retrieval** (`top_k=5`), changing only the
generation step. So the diff is purely prompt + sampling params, not the retrieved context.

| Knob | Baseline (before) | Optimized (after) | Why |
|-----|------|----------|------|
| Prompt template | `BASELINE_PROMPT` (generic, English wording) | `OPTIMIZED_PROMPT` (Russian, 3-5 concise sentences, strict `Sources:` last line, explicit insufficient-context rule) | fixes language drift + citation format for this use case |
| `temperature` | Ollama default (~0.8) | `0.2` | less randomness, more deterministic/stable answers |
| `top_p` | default (~0.9) | `0.9` (explicit) | keeps the sensible nucleus, removes long tail |
| `max_tokens` (`num_predict`) | unset (unbounded) | `160` | caps runaway output; shorter answers |
| Retrieval `top_k` | `5` | `5` (held equal) | isolate the generation change, don't drop sources |
| `num_ctx` | not set (default 4096) | not set (default 4096) | **intentionally equal** — changing it forces an Ollama model reload that dominates CPU wall-clock and hides the real effect |
| Model / quant | `qwen2.5-coder:7b` (Q4_K_M) | same | optional 3rd arm via `--quant-model` (see below) |

### How to read the result

The report is intentionally symmetric: each question has `baseline` and `optimized` blocks, and the
summary aggregates the same fields for both. Use it as an A/B table:

| metric | What it says |
|-----|------|
| `avg_keyword_recall` | whether the answer contains expected concepts from `week_05/eval/questions.json` |
| `source_hit_rate` | whether retrieval found an expected source file |
| `sources_format_rate` | whether the answer ended with a valid `Sources: [...]` line |
| `avg_answer_chars` | whether the optimized answer is shorter / more focused |
| `avg_tokens_per_sec` | pure decode speed from Ollama (`eval_count / eval_duration`) |
| `avg_total_latency_s` | full wall-clock latency, including prompt-eval/prefill |

**Honest read rule:** if recall/format improve but wall-clock does not, report it as a trade-off, not
as a fake speed win. Day 29 is about tuning and measuring, not forcing every knob to win.

### Why "optimized" is not faster here (CPU caveat)

`tokens_per_sec` (from Ollama `eval_duration`) measures only **decode**. It does not include
prompt-eval/prefill: the model first has to process the retrieved chunks before generating the first
answer token. On a CPU-only box, prefill over a few thousand prompt tokens can dominate wall-clock.

The optimizer uses a **neutral warmup** (`"warmup"`, `num_predict=8`) before the measured arms. This
loads the model without warming either the baseline RAG prompt or the optimized RAG prompt. That
makes the comparison fairer: no arm gets a baseline-specific KV-cache advantage.

The takeaway: on CPU the dominant cost is prefill + decode of a 7B, which parameter tuning cannot
fully fix. The real speed levers are a smaller model (`qwen2.5-coder:3b`), a lighter quant, or GPU
offload.

### Quantization (optional 3rd arm)

`qwen2.5-coder:7b` ships pre-quantized (Q4_K_M). "Trying quantization" = compare it against a lighter
quant. Pull it once, then pass `--quant-model`:

```bash
ollama pull qwen2.5-coder:7b-instruct-q3_K_M
uv run python -m week_06.local_rag optimize --limit 2 \
  --quant-model qwen2.5-coder:7b-instruct-q3_K_M
```

Q3_K_M is ~3.8 GB vs ~4.7 GB for Q4_K_M (less RAM, slightly lower quality). If the tag is not pulled,
the quant arm is skipped with a clear message and the run continues. Show resource usage in the demo
with `ollama ps` (SIZE + `PROCESSOR` = CPU/GPU split).

### Run Day 29

```bash
# default: baseline vs optimized on Q4 (no quant arm), writes JSON report
uv run python -m week_06.local_rag optimize --limit 2

# single question, printed side by side (fast, no report) — good for live demo
uv run python -m week_06.local_rag optimize --question "Чем max_tokens отличается от context window согласно материалам?"


# interactive baseline-vs-optimized loop
uv run python -m week_06.local_rag optimize --interactive

# median over N repeats per arm (reduces single-shot noise)
uv run python -m week_06.local_rag optimize --limit 2 --repeats 3
```

Report path:

```text
week_06/eval/day29_optimization_results.json
```

### Metrics in the report

Each arm (`baseline`, `optimized`, optional `quant`) has a symmetric block:

- quality: `avg_keyword_recall`, `source_hit_rate`, `sources_format_rate`, `fallback_count`
- speed: `avg_retrieval_latency_s`, `avg_generation_latency_s`, `avg_total_latency_s`,
  `avg_tokens_per_sec` (decode), `avg_load_seconds`
- shape: `avg_answer_chars`

`sources_format_rate` = fraction of answers whose last non-empty line is a valid `Sources: [...]`
line (accepts both `[C1], [C3]` and `[C1, C3]`, and `Sources: []`).

### Notes

- retrieval is held constant (`top_k=5`) so the comparison isolates the generation change;
- baseline uses Ollama default sampling (non-deterministic); optimized (`temperature=0.2`) is more
  stable run to run;
- `num_ctx` is deliberately not changed between arms — changing it triggers a model reload that
  dominates CPU wall-clock;
- `optimize` does one neutral warmup call (`"warmup"`, `num_predict=8`) before timed runs to load the
  model without warming either RAG prompt;
- wall-clock on CPU is dominated by prompt-eval/decode of the 7B and is noisy at `repeats=1`; use
  `--repeats 3` (median) or a smaller model for steadier numbers.

## Day 30 — Local LLM as a Private Service (VPS-ready)

### Goal

Expose the local LLM as a private network service with:

- HTTP API;
- browser chat UI;
- API key authentication;
- basic limits (`rate limit`, `max context/prompt`);
- network accessibility from outside (VPS/public URL).

### Why Day 30 differs from Day 27

- Day 27: local app for yourself on localhost.
- Day 30: deployable service for external clients over network, with auth and guardrails.

### Architecture

```text
browser/curl
   -> Flask private API (week_06.web_app)
      -> local Ollama endpoint (127.0.0.1:11434)
         -> qwen2.5:3b
```

Only Flask/Caddy is exposed publicly. Ollama itself stays private. The VPS demo defaults
to `qwen2.5:3b` for general chat because it follows short Russian/non-code prompts better
than the code-focused `qwen2.5-coder:3b`. The coder 3B model stays available for code tasks.
`qwen2.5-coder:7b` is optional and was not pulled for the CPU-only VPS demo because it is
too slow for a reliable live walkthrough.

### Env vars

```text
PRIVATE_LLM_API_KEY   required
LLM_PROVIDER          default: Qwen2.5 3B (Ollama, local)
HOST                  default: 0.0.0.0
PORT                  default: 8000
MAX_PROMPT_CHARS      default: 4000
RATE_LIMIT_PER_MIN    default: 10
LLM_TEMPERATURE       default: 0.2
LLM_TOP_P             default: 0.9
LLM_MAX_TOKENS        default: 220
```

### API endpoints

- `GET /api/health` (auth required)
- `POST /api/chat` (auth required)
- `GET /api/history` (auth required)

Compatibility aliases (also auth-required): `/health`, `/ask`, `/history`.

Error contract:

```json
{"error":"...","code":401}
```

### Run locally

Ensure model is pulled:

```bash
ollama pull qwen2.5:3b
ollama pull qwen2.5-coder:3b
```

```bash
# bash
export PRIVATE_LLM_API_KEY=dev-secret
export LLM_PROVIDER="Qwen2.5 3B (Ollama, local)"
export HOST=127.0.0.1
export PORT=8000
export MAX_PROMPT_CHARS=4000
export RATE_LIMIT_PER_MIN=10
export LLM_TEMPERATURE=0.2
export LLM_TOP_P=0.9
export LLM_MAX_TOKENS=220

uv run python -m week_06.web_app
```

### Run on VPS

Use `week_06/deploy/README.md` for full steps.

Recommended VPS for stable 3B demo:

- 4 vCPU / 8 GB RAM (Ubuntu 24.04)

Minimal:

- 2 vCPU / 4 GB RAM (works but slower/riskier)

### What to verify

- Auth:
  - no Bearer key -> `401`
  - valid key -> request succeeds
- Rate limit:
  - repeated requests exceed `RATE_LIMIT_PER_MIN` -> `429` + `Retry-After`
- Max context guard:
  - prompt > `MAX_PROMPT_CHARS` -> `413`
- Stability:
  - 5 sequential requests return stable responses (no crashes)
- Network access:
  - service reachable from external machine/browser over VPS/public URL.

### Copy-paste curl checks

```bash
# health
curl http://127.0.0.1:8000/api/health \
  -H "Authorization: Bearer dev-secret"

# chat
curl http://127.0.0.1:8000/api/chat \
  -H "Authorization: Bearer dev-secret" \
  -H "Content-Type: application/json" \
  -d '{"mode":"general","prompt":"Коротко объясни, что такое локальная LLM"}'

# unauthorized
curl -i http://127.0.0.1:8000/api/health

# rate limit (expect some 429)
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/health \
    -H "Authorization: Bearer dev-secret"
done
```

Max prompt check:

```bash
python - <<'PY' | curl -i http://127.0.0.1:8000/api/chat \
  -H "Authorization: Bearer dev-secret" \
  -H "Content-Type: application/json" \
  --data-binary @-
import json
print(json.dumps({"mode": "general", "prompt": "x" * 5000}))
PY
```

### Verified VPS checks

These checks were run against the public DigitalOcean VPS demo endpoint:

```text
VPS URL: http://139.59.141.72:8000
Model: qwen2.5:3b
Provider: Qwen2.5 3B (Ollama, local)
```

`demo-secret` is a demo value supplied through `PRIVATE_LLM_API_KEY`; real secrets are
runtime environment values and are not committed to code.

Auth rejects missing Bearer token:

```bash
curl -i http://139.59.141.72:8000/api/health
# HTTP/1.1 401 UNAUTHORIZED
# {"code":401,"error":"unauthorized"}
```

Health succeeds with the Bearer token:

```bash
curl -i http://139.59.141.72:8000/api/health \
  -H "Authorization: Bearer demo-secret"
# HTTP/1.1 200 OK
# {"ok":true,"model":"qwen2.5:3b", ...}
```

Chat works through the public HTTP API:

```bash
curl -s http://139.59.141.72:8000/api/chat \
  -H "Authorization: Bearer demo-secret" \
  -H "Content-Type: application/json" \
  -d '{"mode":"general","prompt":"Напиши минимальный Flask route /health, который возвращает {\"ok\": true}."}'
# returns HTTP 200 JSON with text, latency_seconds, tokens_out, tokens_per_sec
```

Max prompt guard rejects oversized prompts:

```bash
python - <<'PY' | curl -i http://139.59.141.72:8000/api/chat \
  -H "Authorization: Bearer demo-secret" \
  -H "Content-Type: application/json" \
  --data-binary @-
import json
print(json.dumps({"mode": "general", "prompt": "x" * 5000}))
PY
# HTTP/1.1 413 REQUEST ENTITY TOO LARGE
# {"code":413,"error":"prompt too large (max 4000 chars)"}
```

Rate limit returns `429` after the configured window is exhausted:

```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    http://139.59.141.72:8000/api/health \
    -H "Authorization: Bearer demo-secret"
done
# 200 ... then 429
```

### Demo flow (Day 30)

1. Start service with `PRIVATE_LLM_API_KEY`.
2. Open browser UI (`/`) and enter API key in page.
3. Check model health.
4. Send a chat request from browser.
5. Send the same through `curl /api/chat`.
6. Show `401` without key.
7. Show `429` rate-limit.
8. Show `413` oversized prompt.
9. Show external access from another device/network.

## Troubleshooting (bash + Ollama)

- `model not found`:
  - run `ollama pull qwen2.5:3b` for the default VPS demo model;
  - run `ollama pull qwen2.5-coder:3b` if you want the code-focused provider too.
- `Connection refused` / API connection error:
  - start Ollama app or run `ollama serve`.
- Too slow / high memory:
  - use `--provider "Qwen2.5 3B (Ollama, local)"`;
  - keep `qwen2.5-coder:7b` for stronger local machines, not the CPU-only VPS demo.
- Python import error:
  - run from repo root with `uv run python -m week_06.main`.
- Day 28 DB not found:
  - build Week 5 index first:
    `uv run python -m week_05.main compare --source "week_05/corpus"`.
- Day 28 no lexical hits:
  - ask a more specific question with terms likely present in the indexed corpus.
- Day 28 cloud side skipped:
  - `no cloud API key for generation` — set a cloud generation key (e.g. `DEEPSEEK_API_KEY`);
  - with `--cloud-retrieval vector`: also needs `OPENAI_API_KEY` to embed the query in the indexed
    vector space (message: `OPENAI_API_KEY missing ...`);
  - either way the local flow still fully satisfies Day 28.

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
| 27 | Integrate local LLM into a real local app (Flask web UI + prompt modes + request history) | `uv run python -m week_06.web_app` | `web_app.py`, `workbench.py`, `templates/workbench.html`, `local_client.py`, `README.md` | done | _link_ |
| 28 | Reuse Week 5 SQLite index for RAG with local lexical retrieval; compare local vs cloud generation on the same context (symmetric metrics); optional full cloud stack via `--cloud-retrieval vector` | `uv run python -m week_06.local_rag ask`, `compare`, `eval` | `local_rag.py`, `README.md`, `week_06/eval/day28_results.json` | done | _link_ |
| 29 | Optimize local LLM generation for the RAG Q&A use case: baseline vs optimized prompt + sampling params (temperature/top_p/max_tokens) on identical retrieval, native Ollama `/api/chat` with tokens/sec + load metrics, optional `--quant-model` arm | `uv run python -m week_06.local_rag optimize --limit 2` | `local_rag.py`, `local_client.py`, `README.md`, `week_06/eval/day29_optimization_results.json` | done | _link_ |
| 30 | Expose local LLM as a private network service (VPS-ready): HTTP API + browser chat + API-key auth + rate limit + max prompt guard + external access checks | `uv run python -m week_06.web_app` | `web_app.py`, `workbench.py`, `templates/workbench.html`, `week_06/deploy/*`, `README.md` | done | _link_ |
