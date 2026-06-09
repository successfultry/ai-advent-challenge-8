# Week 01 — Basics of LLMs & prompting

## Structure

```
week_01/
├── main.py      # entrypoint
├── cli.py       # terminal UI (rich, меню, chat loop)
└── README.md
```

API logic and provider registry live in `shared/` (`shared.client`, `shared.config`).

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

## Day 2 — Response format & control

Control model output via API parameters **and** via prompt text. Compare the results.

### How to demo (3 runs with the same question)

**Run 1 — raw:** just type a question normally. No params, no instructions.

**Run 2 — API-constrained:** type `/params`, set the constraints interactively:
- `max_tokens` — hard limit on output length (e.g. `80`)
- `stop sequence` — a word that triggers generation stop (e.g. `END`)
- `json mode` — force valid JSON output (`y`/`n`)

Then send the same question. The response shows `finish_reason` (`stop` vs `length`)
and token usage. Type `/params off` when done.

**Run 3 — prompt-constrained:** use `/params off` (raw mode) and write the constraints
yourself in the message text. Use `/hint` to see a template. Example:

> Расскажи о Москве. Ответь в JSON. Не больше 50 слов. Закончи словом END.

New commands:

| Command | Action |
|---------|--------|
| `/params` | interactively set `max_tokens`, `stop`, `json` for next messages |
| `/params off` | disable params, back to raw mode |
| `/hint` | show a copy-pasteable prompt-constrained template (RU + EN) |

UX details:
- When params are active the prompt shows them: `You [max_tokens=30, stop=['END']]:`
- When you type `/params` with existing chat history, a tip reminds to `/clear` first
  so prompt tokens stay low and comparison is cleaner.

Key insight: API parameters (`max_tokens`, `stop`) are **hard guarantees** — the API
enforces them regardless of what the model wants. Prompt instructions are **soft** — the
model may ignore them. `finish_reason=length` = cut mid-sentence; `stop` = ended cleanly.

**json mode note:** `response_format=json_object` requires the word «json» somewhere in the
messages (OpenAI and DeepSeek enforce this). When `json=on` is active, the CLI automatically
injects a system instruction so any prompt works without you writing «json» manually.

DeepSeek R1 (`deepseek-reasoner`) ignores `stop` and `temperature` — use `deepseek-chat`
or `gpt-4o-mini` for this comparison.

### Demo steps (run in order)

Start with `uv run python -m week_01.main`, pick `DeepSeek V3` or `GPT-4o mini`
(not R1), then:

**1. Raw — no limits**
```
Расскажи о Москве
```
Long free-form answer. Streamed; no finish_reason shown.

**2. max_tokens — hard cut**
```
/clear
/params      → max_tokens: 30 · stop: (empty) · json: n
Расскажи о Москве
```
Answer cut mid-sentence. `finish: length`.

**3. stop sequence — cut at marker**
```
/clear
/params      → max_tokens: (empty) · stop: ###END### · json: n
Расскажи о Москве и закончи маркером ###END###
```
Answer ends right before `###END###`; the marker is NOT in the text. `finish: stop`.

**4. json — format control**
```
/clear
/params      → max_tokens: (empty) · stop: (empty) · json: y
Дай 3 факта о Москве в JSON
```
Valid JSON object. `finish: stop`.

**5. broken json — limit too small**
```
/clear
/params      → max_tokens: 10 · json: y
Дай 3 факта о Москве в JSON
```
JSON cut mid-object → invalid. `finish: length`. (Shows: `stop`/json are pointless if
`max_tokens` is too small to fit the structure.)

**6. prompt-constrained — same control via text only**
```
/params off
/hint        → copy the template, edit, send as a normal message
```
The model decides whether to obey — soft control, no API params.

## Day 3 — Different reasoning strategies

Same task solved four ways, side by side, to show how the prompting technique
changes the quality and style of the answer.

### Techniques

| # | Name | What the prompt does |
|---|------|----------------------|
| 1 | **Direct** | question as-is, no instructions |
| 2 | **Chain of Thought** | «solve step by step, show reasoning» |
| 3 | **Meta-prompt** | 2 API calls: first ask model to *write the best prompt* for the task, then send that prompt. The generated prompt is printed so you can see what the model wrote. |
| 4 | **Experts panel** | system prompt assigns 3 roles (Analyst, Engineer, Critic); each gives their perspective |

Techniques run in order 1→2→3→4; each prints its answer, `finish_reason` and token usage.
At the end `/solve` prints the total token cost of the whole experiment.

### Commands

```
/solve <task>    run all 4 techniques, print each result with usage
/judge           send all 4 results to the model; it rates and picks the best
```

Technique instructions auto-switch language: Cyrillic question → Russian prompts,
otherwise English (keeps the answer in the same language as the question).

No `/clear` needed before `/solve` — each technique sends an **independent** request
with its own fresh `messages`. The main chat history is not touched.

`/judge` is optional but gives a clean on-screen verdict for the video.

### Demo

```
/solve In a room there are 3 switches and 1 bulb in another room. You can enter the other room only once. How do you find which switch controls the bulb?
/solve В одной комнате есть 3 выключателя, а в другой комнате - 1 лампочка. Вы можете войти в другую комнату только один раз. Как определить, какой выключатель управляет лампочкой?
/judge
```


Or use an analytical task where different perspectives actually diverge:

```
/solve What is the most important skill for a software engineer in 2026?
/solve Какой навык является самым важным для инженера-программиста в 2026 году?
/judge
```

---

## Day 4 — Temperature

Send the same prompt at `temperature = 0 / 0.7 / 1.2 / 2.0`, 3 runs each, and compare
accuracy, creativity, and diversity across temperatures.

```
/temp <question>
```

Each temperature runs **3 times** (`DEFAULT_REPEATS = 3`) with a `max_tokens=150` cap —
this prevents `temp=2.0` from burning thousands of tokens on incoherent output while still
showing the full degradation effect. The cap is intentional: equal length across temps makes
the diversity axis more comparable.

- `temp=0` → all runs are nearly **identical** (deterministic, reproducible)
- `temp=1.2+` → each run is **noticeably different** (diversity grows)
- `temp=2.0` → degradation: incoherent words, mixed languages, gibberish (capped at 150 tokens)

> **Model note:** use `DeepSeek V3` (`deepseek-chat`) or `GPT-4o` — both respect
> `temperature`. `DeepSeek R1` (reasoning model) ignores temperature; use `reasoning_effort`
> for that one.

### Debug mode

```
/debug    toggle raw request JSON output (off by default)
```

When enabled, every API call prints the exact JSON payload that flies to the REST endpoint —
useful for understanding what parameters are actually sent.

### Demo

```
/temp Напиши короткое стихотворение о программировании
/temp Write a one-paragraph story about a robot discovering music
/debug
/temp What color is the sky?
```

Recommended flow for the video: show `temp=0` (3 identical runs), then `temp=1.2`
(3 different runs), finish with `temp=2.0` (chaos). Mention use-cases at the end:
- `0` → extraction, classification, reproducible outputs
- `0.7` → default balance (chat, explanations)
- `1.2` → brainstorming, naming, creative writing
- `2.0` → demonstrates breakdown; not useful in practice

---

## Day 5 — Model tiers: weak / medium / strong

Run the same question on three models that differ in size and compare response quality,
speed, and cost.

### What "weak / medium / strong" means

| Tier | Approximate size | Example here |
|------|-----------------|--------------|
| **weak** | up to ~8B parameters | `llama-3.1-8b-instant` via Groq |
| **medium** | ~70B parameters | `llama-3.3-70b-versatile` via Groq |
| **strong** | frontier (400B+, closed-source) | `gpt-4o` via OpenAI |

Parameter count is stated in the model name for open models (Llama `-8b`, `-70b`).
OpenAI does not publish sizes — `gpt-4o` is classified as strong by benchmarks, not by
a known param count.


### Command

```
/bench <question>
```

Each tier runs sequentially with the same fixed params (`temperature=0.7`,
`max_tokens=500`). Each model's full answer is printed as soon as it arrives
(weak → medium → strong), then a summary Rich table with all metrics is shown last:

```
tier              | provider         | time  | ↑ in | ↓ out | total tok | cost USD | finish | preview
weak   (~8B)      | Llama 8B (Groq)  | 0.8s  |  42  |  89   |    131    | $0.00001 | stop   | …
medium (~70B)     | Llama 70B (Groq) | 2.3s  |  42  |  156  |    198    | $0.00011 | stop   | …
strong (frontier) | GPT-4o           | 4.7s  |  42  |  201  |    243    | $0.00213 | stop   | …
```

Cost is calculated from `PRICING` in `config.py`
(USD per 1M tokens). Sources: [OpenAI pricing](https://platform.openai.com/docs/pricing),
[Groq pricing](https://groq.com/pricing), [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing).

`/debug` shows the exact JSON payload sent to each provider before the call.

### Demo flow

```
/bench Есть Python-библиотека fastmatrix для умножения матриц. Как установить и пример?
/bench У Ани 2 яблока, у Васи 3 груши. Сколько всего фруктов? Потом Аня съела одно яблоко.
/bench У меня грязная машина. Мойка в 100 метрах. Ехать на машине или дойти пешком?
```

Good demo questions trigger hallucinations or logic errors on weak models but not on strong.
In practice: `fastmatrix` makes the weak (and sometimes medium) model invent a non-existent
library, while the strong one admits it doesn't know it. The car-wash question trips the weak
model into a confused answer, while medium/strong correctly reason "100 m → just walk".

---

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 1 | First LLM request via API (streaming CLI) | chat, `/switch`, `/clear` | `client.stream_response`, `cli.chat_loop` | done | _link_ |
| 2 | Response format & control | `/params`, `/hint` | `client.get_response`, `cli.ask_params` | done | _link_ |
| 3 | Reasoning strategies | `/solve`, `/judge` | `techniques.py`, `cli.run_solve` | done | _link_ |
| 4 | Temperature sweep | `/temp`, `/debug` | `cli.run_temp`, `cli.print_request` | done | _link_ |
| 5 | Model tiers (weak/medium/strong) | `/bench` | `config.BENCH_TIERS`, `client.timed_response`, `cli.run_bench` | done | _link_ |

All days share one codebase; the table maps each day to its commands and the modules that
implement them. 
