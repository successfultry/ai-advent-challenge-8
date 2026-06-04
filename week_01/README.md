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

DeepSeek R1 (`deepseek-reasoner`) ignores `stop` and `temperature` — use `deepseek-chat`
or `gpt-4o-mini` for this comparison.

### Demo steps (run in order)

Start with `uv run python -m week_01.main`, pick `DeepSeek Chat` or `GPT-4o mini`
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

## Progress

| Day | Task | Status | Video |
|-----|------|--------|-------|
| 1 | First LLM request via API (streaming CLI) | done | _link_ |
| 2 | Response format & control (`/params`, `/hint`) | done | _link_ |
