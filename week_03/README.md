# Week 03 — Memory, State & Stateful Agents

## Structure

```
week_03/
├── main.py            # entrypoint (argparse --user, --chat, --fresh, --auto)
├── cli.py             # terminal UI (rich, command loop)
├── agent.py           # Agent — orchestrator: ShortTermStore + build_system + LLM
├── memory.py          # ProfileStore (Markdown), WorkingStore (JSON), ShortTermStore (JSON)
├── state.py           # TaskState enum, validate_transition(), next_stage(), typed result types
├── prompt_builder.py  # build_system / build_stage_system, STAGE_PROMPTS
├── pipeline.py        # run_pipeline() — deterministic 4-stage FSM
└── stats.py           # TokenStats (session totals)
```

Three memory layers — **each layer lives in its own folder**:

| Layer | File | Format | Scope |
|-------|------|--------|-------|
| short-term | `data/short_term/<user>_<chat>.json` | JSON | one chat/session |
| working | `data/working/<user>_<taskid>.json` | JSON | one task (may span chats) |
| long-term | `data/long_term/<user>.md` | Markdown | all chats/tasks of the same user |

Active task is tracked in `data/active_task/<user>.json` (pointer file, survives restarts).

```
data/
├── short_term/   <user>_<chat>.json
├── working/      <user>_<taskid>.json
├── long_term/    <user>.md
└── active_task/  <user>.json
```

## Run

```bash
# Default user + chat
uv run python -m week_03.main

# Specific user
uv run python -m week_03.main --user alice

# Specific user + chat
uv run python -m week_03.main --user alice --chat session2

# Fresh session (empty short-term; profile + task still loaded)
uv run python -m week_03.main --user alice --fresh
```

Requires a `.env` in the repo root with at least one key:

```
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...
```

---

## Day 11 — Stateful Agent with 3-Layer Memory

A stateful CLI agent where **each memory layer has a separate file**, and the demo proves
that each layer independently affects model answers.

### How it works

- `ProfileStore` reads/writes `data/long_term/<user>.md` — human-editable Markdown
  (claude.md / AGENTS.md style). Key = `## section`, value = body below it.
- `WorkingStore` reads/writes `data/working/<user>_<taskid>.json` — holds task name,
  state machine state, plan, decisions, notes, validation.
- `ShortTermStore` reads/writes `data/short_term/<user>_<chat>.json` — raw message history.
- On **every model call**, `prompt_builder.build_system()` rebuilds the system prompt fresh
  from `profile + active_task`. Short-term is appended as messages after it. No caching.
- `/clear` only empties short-term. Profile and task files are not touched.
- Active task survives restarts via `data/active_task/<user>.json`.

### Task state machine

```
[/task new] → PLANNING ⇄ EXECUTION ⇄ VALIDATION → DONE
```

Forward: `PLANNING → EXECUTION → VALIDATION → DONE`. Pragmatic rollbacks are allowed:
`EXECUTION → PLANNING` (plan was incomplete) and `VALIDATION → EXECUTION` (found a bug).
Everything else (e.g. `PLANNING → DONE`) is rejected with a typed `TransitionError` (no crash).
`NONE → PLANNING` only via `/task new`, never via `/task status`. `/task reset` wipes the
current task back to an empty PLANNING state.

### In-chat commands

| Command | Action |
|---------|--------|
| `/profile show` | print long-term profile |
| `/profile set <k> <v>` | upsert key in long-term profile |
| `/task new <name>` | create task in PLANNING + set active pointer |
| `/task show` | print current working memory |
| `/task status <state>` | advance task state (validated) |
| `/task plan <text>` | set the task plan (PLANNING) |
| `/task decision <text>` | append an accepted decision |
| `/task note <text>` | append note to working memory |
| `/task validate <text>` | set validation result (VALIDATION) |
| `/task reset` | wipe task content, return to PLANNING |
| `/clear` | clear short-term only (profile + task untouched) |
| `/switch` | switch provider/model (all memory preserved) |
| `/help` | show commands |
| `exit` / `quit` | quit |

### Demo (for the video)

```bash
uv run python -m week_03.main --user alice --chat s1
```

**Step 1 — populate long-term profile (developer config):**
```
/profile set language Python
/profile set stack "Python 3.12, uv, ruff"
/profile set style "terse, no narrating comments"
/profile set testing "pytest, no mocks unless necessary"
/profile set forbidden "no FastAPI unless asked"
/profile show
```
Check `data/long_term/alice.md` — readable Markdown, editable by hand (claude.md / AGENTS.md style).

**Step 2 — create a task (working memory):**
```
/task new "http-server"
```
Check `data/working/alice_http-server.json` and `data/active_task/alice.json`.

**Step 3 — model answer reflects profile + task context:**
```
How should I structure the request handler?
```
Answer is in Python, references `http.server`, respects task context.

**Step 4 — fill working fields (plan / decision / note / validation):**
```
/task plan "Build minimal HTTP server with stdlib only"
/task decision "Use BaseHTTPRequestHandler instead of raw sockets"
/task note "use http.server.BaseHTTPRequestHandler"
/task status EXECUTION
/task status VALIDATION
/task validate "Basic GET flow works, proceed to next iteration"
```
Check `data/working/alice_http-server.json` — all these fields are saved in working memory.
They are injected into the system prompt on each request via `prompt_builder`.

**Step 5 — try an invalid transition + state rollbacks:**
```
/task status PLANNING        # → Invalid from VALIDATION (allowed: EXECUTION or DONE)
/task status EXECUTION       # bug found → roll back (allowed)
/task status PLANNING        # plan incomplete → roll back further (allowed)
/task status DONE            # → Invalid: PLANNING → DONE. Allowed from PLANNING: EXECUTION
```
Forward and pragmatic rollbacks work; illegal jumps are still rejected.
(Re-advance to `EXECUTION` before continuing the demo.)

**Step 6 — /clear only wipes short-term:**
```
/clear
```
→ "Short-term cleared. Profile and task untouched."
Check files: `data/short_term/alice_s1.json` is empty; working + long_term unchanged.

**Step 7 — model still recalls task + profile after /clear:**
```
What are we doing and what have we decided?
```
→ mentions http-server task, EXECUTION state, BaseHTTPRequestHandler note, Python constraint.
Short-term was empty but working + long_term are injected into system prompt.

**Step 8 — restart; profile + task reloaded from disk:**
```
exit
```
```bash
uv run python -m week_03.main --user alice --chat s1
```
→ banner: "Resumed task: http-server (EXECUTION)"
Ask anything — task and profile are alive.

**Step 9 — different chat, same task (working spans multiple chats):**
```bash
uv run python -m week_03.main --user alice --chat s2
```
→ "Resumed task: http-server (EXECUTION)" — same working memory, fresh short-term.
```
What are we working on?
```
→ knows the task and note despite `data/short_term/alice_s2.json` being empty.

**Step 10 — --fresh flag:**
```bash
uv run python -m week_03.main --user alice --chat s1 --fresh
```
→ banner shows "fresh session" — short-term starts empty in memory.
Profile + task still loaded. First message overwrites the on-disk short-term file.

### File snapshots (after demo)

**`data/long_term/alice.md`**
```markdown
# Profile: alice

## language
Python

## stack
Python 3.12, uv, ruff

## style
terse, no narrating comments

## testing
pytest, no mocks unless necessary

## forbidden
no FastAPI unless asked
```

**`data/working/alice_http-server.json`**
```json
{
  "version": 1,
  "task_id": "http-server",
  "name": "http-server",
  "state": "EXECUTION",
  "plan": "",
  "decisions": [],
  "notes": ["use http.server.BaseHTTPRequestHandler"],
  "validation": ""
}
```

**`data/active_task/alice.json`**
```json
{"active_task": "http-server"}
```

**`data/short_term/alice_s2.json`** (different chat — proves short-term independence)
```json
{"version": 1, "messages": []}
```

---

## Day 12 — Personalization

Personalization layer built on top of the Day 11 long-term memory.
Three ways to populate a user profile: manual edits, first-run onboarding (no LLM, default on),
and opt-in auto-capture via LLM (requires `--learn`).

### How it works

- `prompt_builder.build_system` now renders four known categories as **dedicated sections**:
  `## Style`, `## Format`, `## Constraints`, `## Forbidden (never do)`.
  Any other keys appear under `## User Profile`. All are HARD CONSTRAINTS for the model.
- **First-run onboarding**: if `data/long_term/<user>.md` is empty at startup, the CLI
  asks six fixed questions (language, stack, style, format, constraints, forbidden).
  Answers are written immediately via `ProfileStore.upsert`. Skipped questions leave those keys unset.
  Skippable via `--no-onboard` (needed for Day 11 demo reproducibility).
- **Learn mode** (`--learn` or `/profile learn on`): after printing each assistant answer (not on
  `/` commands), one best-effort LLM call with `response_format=json_object` extracts durable
  preferences from the user's message. All extracted keys are saved (e.g. one turn can yield
  `language=Go` and `forbidden=never in Python`). Any LLM/parse failure silently returns `{}` —
  the main chat is never blocked.
- `ProfileStore` API unchanged (`load/save/upsert`); Markdown backing unchanged.

### New CLI flags

```bash
# enable auto-capture of durable preferences from chat
uv run python -m week_03.main --user alice --learn

# skip first-run onboarding (Day 11 parity)
uv run python -m week_03.main --user alice --no-onboard
```

### New in-chat commands (Day 12)

| Command | Action |
|---------|--------|
| `/profile forget <k>` | remove key from long-term profile |
| `/profile learn on\|off` | toggle auto-capture at runtime |
| `/profile onboard` | rerun onboarding questionnaire manually |

---

### Demo Day 12

> **Precondition:** clean up old data files before running this demo:
> ```bash
> del data\long_term\alice.md
> del data\long_term\bob.md
> del data\short_term\alice_d12.json
> del data\short_term\bob_d12.json
> ```
> Day 11 demo used `alice` with a manually-set profile — this demo creates both users from scratch via onboarding.

**Step 1 — Onboard alice (Python developer):**
```bash
uv run python -m week_03.main --user alice --chat d12
```
Banner shows `onboard=first-run`. Answer:
```
Primary language (e.g. Python, Go, Rust): Python
Preferred stack / frameworks: Python 3.12, uv, ruff
Answer style (terse / detailed / with examples): terse, no narrating comments
Format preference (code blocks, comments, etc.): [Enter — skip]
Hard constraints (stdlib only, no external libs, etc.): stdlib only unless asked
Forbidden (never do this): no FastAPI unless asked
```
`Onboarding done. Profile saved.`
Open `data/long_term/alice.md` — human-readable Markdown with explicit sections.
```
exit
```

**Step 2 — Onboard bob (Go developer):**
```bash
uv run python -m week_03.main --user bob --chat d12
```
Banner shows `onboard=first-run`. Answer:
```
Primary language (e.g. Python, Go, Rust): Go
Preferred stack / frameworks: Fiber
Answer style (terse / detailed / with examples): terse
Format preference (code blocks, comments, etc.): [Enter — skip]
Hard constraints (stdlib only, no external libs, etc.): [Enter — skip]
Forbidden (never do this): no python
```
`Onboarding done. Profile saved.`
Open `data/long_term/bob.md`.
```
exit
```

**Step 3 — Same question, different profiles → different answers:**
```bash
uv run python -m week_03.main --user alice --chat d12
```
```
Write a simple hello world web server.
```
→ Gets a **Python + http.server** answer.
```
exit
```
```bash
uv run python -m week_03.main --user bob --chat d12
```
```
Write a simple hello world web server.
```
→ Gets a **Go + Fiber** answer. Same question, different profile → different answer.

**Step 4 — Negative case: learn mode OFF (Day 11 parity):**
Still as bob (no `--learn`):
```
From now on use Rust.
```
→ Agent answers but `data/long_term/bob.md` **is unchanged**. Open the file to confirm — Rust does not appear.
No extra LLM extraction calls were made. This is the default behavior; it reproduces Day 11 exactly.

Also try a command typo to see the new guard:
```
/profile forgen forbidden
```
→ `Unknown command: /profile forgen forbidden  Type /help.` — it was NOT sent to the LLM.

**Step 5 — Enable learn mode and capture multiple preferences:**
```
/profile learn on
```
`Learn mode: on (auto-capture enabled)`
```
Always answer in Go, never in Python.
```
→ Agent answers normally. After the answer you see **one or more** learned preferences, e.g.:
```
Learned: language=Go
Learned: forbidden=never in Python
```
Both keys are saved in a single turn. Check `data/long_term/bob.md` — both sections are updated.
Next question uses the new values automatically (system prompt is rebuilt every turn).

**Step 6 — `/profile forget` removes a key:**
```
/profile forget forbidden
```
Open `data/long_term/bob.md` — `forbidden` section is gone.
```
Write a hello world web server.
```
→ Answer no longer has the `no python` constraint.

**Step 7 — `/profile onboard` reruns the questionnaire:**
```
/profile onboard
```
→ Asks the same fixed questions. Empty answers leave existing keys unchanged.
Only answered keys are overwritten.

### File snapshot after Demo Day 12

**`data/long_term/alice.md`**:
```markdown
# Profile: alice

## language
Python

## stack
Python 3.12, uv, ruff

## style
terse, no narrating comments

## constraints
stdlib only unless asked

## forbidden
no FastAPI unless asked
```

**`data/long_term/bob.md`** (after steps 2–5, before step 6):
```markdown
# Profile: bob

## language
Go

## stack
Fiber

## style
terse

## forbidden
never in Python
```

---

## Day 13 — Task State Machine

### Architecture

Task execution is a **deterministic finite state machine** with 4 stages, each backed by its own
`Agent` instance (own system prompt, own short-term context). Transitions are decided by code in
`state.py`, never by the LLM.

```
PLANNING ──► EXECUTION ──► VALIDATION ──► DONE
    ▲             │              │
    └─────────────┘◄─────────────┘  (rollback edges)
```

Allowed transitions:
- `PLANNING → EXECUTION`
- `EXECUTION → VALIDATION | PLANNING` (rollback if plan incomplete)
- `VALIDATION → DONE | EXECUTION | PLANNING` (rollback if plan was wrong)
- `DONE → (none)`

The next stage is chosen **in code** from the artifact, never by the LLM picking a state name:
VALIDATION reads its own `status` field — `PASS → DONE`, `FAIL → EXECUTION` (rollback). An
EXECUTION⇄VALIDATION loop is bounded by a stage-run budget; on exhaustion the pipeline pauses
for manual review instead of burning tokens.

**6 agent cognition stages** (perception → memory → reasoning → planning → action → feedback) ≠
**4 task pipeline stages** (PLANNING / EXECUTION / VALIDATION / DONE). The cognition cycle runs
inside every individual LLM call; the 4 pipeline stages are at the task orchestration level.

### Artifact contract

Each stage emits **strict JSON** (enforced by `response_format=json_object`), persisted to
working memory and fed forward into the next stage's system prompt:

| Stage | Required JSON keys |
|-------|--------------------|
| PLANNING | `plan[]`, `current_step`, `expected_action` |
| EXECUTION | `result`, `artifacts[]`, `current_step`, `expected_action` |
| VALIDATION | `status` (`PASS`/`FAIL`), `issues[]`, `current_step`, `expected_action` |
| DONE | `summary`, `current_step` (`"done"`), `expected_action` (`"none"`) |

Malformed output triggers **one inline retry**. If still invalid: state does not advance,
`expected_action` is set to `"retry stage output format"`, pipeline pauses.

### Pause is lossless

State is saved to `WorkingStore` **after each successful stage** — before asking the user to
continue. On `pause` answer or process exit, restarting with `/resume` continues from the
persisted stage without re-explaining anything.

### New CLI commands

| Command | Effect |
|---------|--------|
| `/run <description>` | Create task + run full pipeline (PLANNING→DONE) |
| `/resume` | Continue active task from its persisted stage |
| `/auto on\|off` | Toggle auto-advance (skip per-stage confirmations) |

`--auto` flag for the same effect from startup.

### Demo

**Preconditions** (clear previous run data, adjust user as needed):
```bash
rm -f data/working/alice_*.json data/short_term/alice_*.json
uv run python -m week_03.main --user alice --no-onboard
```

**1. End-to-end (ask mode — confirms at each stage):**
```
/run write a Python HTTP server using stdlib only
```
→ PLANNING agent emits a JSON plan, asks "Proceed to EXECUTION? [ok/pause/abort]"
→ Type `ok`, EXECUTION agent emits code inline, asks "Proceed to VALIDATION?"
→ Type `ok`, VALIDATION agent returns `status=PASS`, transitions to DONE; the DONE agent emits a
summary. `Pipeline complete.`

**2. End-to-end (auto mode — no confirmations):**
```
/auto on
/run write a Python HTTP server using stdlib only
```
→ Runs PLANNING → EXECUTION → VALIDATION → DONE without pausing.

**3. Validation FAIL → rollback (the key FSM feature):**
Give a task with a forbidden-tech trap so the validator fails the first attempt:
```bash
uv run python -m week_03.main --user alice --no-onboard
```
```
/profile set forbidden no third-party libs, stdlib only
/auto on
/run write a web server (the executor may reach for Flask — validation must catch it)
```
→ If EXECUTION uses a forbidden lib, VALIDATION returns `status=FAIL`, prints
`Validation FAILED — rolling back to EXECUTION`, and re-runs EXECUTION. State never reaches DONE
on a FAIL. (Bounded by the stage-run budget — see Architecture.)

**4. Deterministic transition is enforced (LLM can't skip stages):**
```
/task new quick task
/task status done
```
→ Rejected: `Invalid: PLANNING → DONE. Allowed from PLANNING: EXECUTION`. The FSM in `state.py`
is the single source of truth, even for manual commands. (`/run` enters the pipeline immediately,
so use `/task new` here to stay on the CLI prompt.)

**5. Pause and resume (lossless, no re-explaining):**
```
/run write a Python HTTP server using stdlib only
```
→ After PLANNING, type `pause`. Then exit (`exit`).
```bash
uv run python -m week_03.main --user alice --no-onboard
```
```
/task show      # state=EXECUTION, current_step/expected_action restored from disk
/resume         # continues from EXECUTION — the plan is reloaded from working memory
```

**6. Per-stage context isolation:**
After a run, inspect short-term files — each stage has its OWN history, nothing shared:
```bash
ls data/short_term/<taskid>_PLANNING.json \
   data/short_term/<taskid>_EXECUTION.json \
   data/short_term/<taskid>_VALIDATION.json
```

**7. Inspect persisted state:**
```
/task show
```
→ Shows `current_step`, `expected_action`, `updated_at` alongside plan / decisions / notes /
the `[summary]` note from the DONE stage.

**8. Back-compat:** a `data/working/*.json` written by Day 11/12 (without `current_step`,
`expected_action`, `last_stage_output`, `updated_at`) still loads — missing fields default to
empty and are filled on the next save.

---

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 11 | Stateful agent with 3-layer memory (short-term / working / long-term), active-task pointer, state machine | `/profile set/show`, `/task new/show/status/note/reset`, `/clear`, `--fresh` | `memory.py`, `state.py`, `prompt_builder.py`, `agent.py`, `stats.py`, `cli.py`, `main.py` | done | _link_ |
| 12 | Personalization: structured profile, onboarding, opt-in LLM auto-capture, multi-user demo | `/profile forget/learn/onboard`, `--learn`, `--no-onboard` | `learn.py`, `prompt_builder.py`, `cli.py`, `main.py` | done | _link_ |
| 13 | Task state machine: 4 stage-agents, deterministic FSM, artifact contracts, pause/resume, auto mode | `/run`, `/resume`, `/auto on\|off`, `--auto` | `pipeline.py`, `state.py`, `prompt_builder.py`, `memory.py`, `cli.py`, `main.py` | done | _link_ |
| 14 | — | — | — | — | — |
| 15 | — | — | — | — | — |

All days share one codebase; the table maps each day to its commands and the modules that implement them.
