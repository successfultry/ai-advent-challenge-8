# Week 05 — RAG / Document Indexing

## Structure

```text
week_05/
├── main.py                     # entrypoint: uv run python -m week_05.main
├── cli.py                      # commands: index / compare / stats / ask / eval
├── models.py                   # Document, Chunk, EmbeddedChunk, IndexRun, stats dataclasses
├── documents.py                # file ingestion: md/txt/py/pdf -> plain text documents
├── chunking.py                 # fixed-size and structure-aware chunking strategies
├── embeddings.py               # OpenAI embedding provider + retry helpers
├── index_store.py              # SQLite schema + run/chunk/cache persistence
├── indexer.py                  # pipeline orchestration: load -> chunk -> embed -> store
├── retrieval.py                # query embedding + cosine retrieval over SQLite chunks
├── rag_qa.py                   # plain / rag answer modes and prompt assembly
├── eval.py                     # 10-question plain vs rag evaluation
├── eval/questions.json         # control questions dataset
└── tests/
    ├── test_chunking.py
    ├── test_store_and_indexer.py
    ├── test_retrieval.py
    └── test_rag_qa_eval.py
```

No `__init__.py` in `week_05/` (PEP 420 namespace package), same run style as earlier weeks:
`uv run python -m week_05.main`.

## Base Setup

```bash
uv sync
```

Day 21 uses `pypdf` for PDF text extraction. It is already added to project dependencies:

```bash
uv add pypdf
```

For real embedding calls and generation calls, put provider keys in local `.env`:

```bash
OPENAI_API_KEY=...
GROQ_API_KEY=...
DEEPSEEK_API_KEY=...
```

`GROQ_API_KEY` is used by earlier chat-model flows (`Llama 8B/70B on Groq`), but the current
Day 21 embedding implementation does not use Groq.

## Embedding Models

Current implementation uses the OpenAI embeddings endpoint.

| Model | Dimensions | Cost | When to use |
|-------|------------|------|-------------|
| `text-embedding-3-small` | 1536 | cheaper | default; good enough for Day 21 demo and most RAG prototypes |
| `text-embedding-3-large` | 3072 | more expensive | better retrieval quality; use when accuracy matters more than cost/storage |

Default model:

```bash
text-embedding-3-small
```

Use the stronger OpenAI model:

```bash
uv run python -m week_05.main compare --source "week_05/corpus" --model text-embedding-3-large
```

Notes:

- `text-embedding-3-small` is not a fake/test model; it is the current cheap OpenAI embedding
  default.
- `text-embedding-3-large` is the stronger OpenAI option and roughly doubles vector storage
  (`3072` dimensions instead of `1536`).
- Changing embedding model means old and new vectors should not be mixed for similarity search.
  This code stores `embedding_model`, `embedding_dim`, and `embedding_norm` per run/chunk.

## Ollama / Local Embeddings

Ollama is local inference. It does not use `OPENAI_API_KEY` or `GROQ_API_KEY`.

Typical local embedding models:

| Ollama model | Dimensions | Notes |
|--------------|------------|-------|
| `nomic-embed-text` | 768 | solid default, small local model |
| `mxbai-embed-large` | 1024 | stronger English retrieval model |
| `bge-m3` | 1024 | multilingual / long-document friendly |

To use Ollama embeddings, install/run Ollama and pull an embedding model:

```bash
ollama pull nomic-embed-text
# or
ollama pull mxbai-embed-large
# or
ollama pull bge-m3
```

Then add an Ollama embedding provider that calls the local API:

```text
POST http://localhost:11434/api/embed
model=<ollama embedding model>
input=<list of chunk texts>
```

This is not implemented in Day 21 yet. Current Day 21 code is OpenAI-only for embeddings.
Groq/Llama can still be useful later for answer generation, but embeddings need a real embedding
model/provider.

---

## Day 21 — Document Indexing

### Goal

Build a local index from real documents:

- load README/articles/code/PDF as text
- split documents into chunks
- generate embeddings
- store chunks, embeddings, and metadata
- compare two chunking strategies

### Supported Inputs

| Extension | Loader | Metadata |
|-----------|--------|----------|
| `.md` | text loader | `language=markdown` |
| `.txt` | text loader | `language=text` |
| `.py` | text loader | `language=python` |
| `.pdf` | `pypdf` extraction | `language=pdf_text` |

Broken or empty files are skipped with warnings. One bad file must not crash the whole indexing
run.

### Chunking Strategies

| Strategy | How it works | Trade-off |
|----------|--------------|-----------|
| `fixed` | fixed character window with overlap | predictable size, can cut through sections |
| `structure` | markdown headings, Python `ast` class/def blocks, paragraph fallback | better sections/citations, uneven sizes |

Each chunk stores:

- `source`
- `title`
- `section`
- `chunk_id`
- `extension`
- `language`
- `content_hash`
- `start_char` / `end_char`

### Storage

SQLite DB path:

```text
data/week_05/rag_index.sqlite
```

Tables:

| Table | Purpose |
|-------|---------|
| `meta` | schema version |
| `index_runs` | one row per index run/strategy/model |
| `chunks` | chunk text, metadata, embedding JSON, embedding dimensions/norm |
| `embedding_cache` | reusable embeddings keyed by `(text_hash, model)` |

SQLite is used instead of FAISS for Day 21 because it is inspectable, portable, and enough for
small local corpora. FAISS is not needed to satisfy Day 21.

### Run (bash)

Clean local demo DB:

```bash
rm -f data/week_05/rag_index.sqlite
```

Run both strategies and compare. This does real indexing, embedding generation, SQLite writes,
and sample output:

```bash
uv run python -m week_05.main compare --source "week_05/corpus"
```

Print DB stats:

```bash
uv run python -m week_05.main --db "data/week_05/rag_index.sqlite" stats
```

Index one strategy at a time (optional):

```bash
uv run python -m week_05.main index --source "week_05/corpus" --strategy fixed
uv run python -m week_05.main index --source "week_05/corpus" --strategy structure
```

Use the stronger OpenAI embedding model:

```bash
uv run python -m week_05.main compare --source "week_05/corpus" --model text-embedding-3-large
```

Cheap test run:

```bash
uv run python -m week_05.main compare --source "week_05/corpus" --limit 120
```

Optional dry run: no API calls and no SQLite writes:

```bash
uv run python -m week_05.main compare --source "week_05/corpus" --dry-run
```

### What To Verify

- `documents=N` is non-zero.
- `chunks=N` is non-zero for both strategies.
- `missing_embeddings=0` on a healthy real run.
- `cache_hits` increases on repeated runs with the same model/text.
- SQLite DB exists at `data/week_05/rag_index.sqlite` after a real run.
- A PDF source appears in output when the source folder includes `.pdf`.
- Fixed and structure strategies produce different chunk counts/average lengths.

### Troubleshooting

- `Missing env var: OPENAI_API_KEY` -> add `OPENAI_API_KEY` to local `.env`.
- `Skipping unreadable file ...` -> file is broken or wrong encoding; fix source file and rerun.
- `missing_embeddings > 0` -> transient provider/API issue; rerun command (cache will reuse finished
  chunks).
- `chunks=0` -> source path has no supported non-empty files (`.md`, `.txt`, `.py`, `.pdf`).
- `stats` rejects `--db` -> put global `--db` before the command:
  `uv run python -m week_05.main --db "data/week_05/rag_index.sqlite" stats`.

### Example Output

Real compare shape:

```text
Comparing strategies for source=week_05/corpus dry_run=False limit=None

[fixed] run_id=fixed-...
documents=10 chunks=236 missing_embeddings=0
cache_hits=0 api_calls=3 avg_chunk_chars=1174.5
estimated_volume: chars=277183 approx_tokens=69295

[structure] run_id=structure-...
documents=10 chunks=330 missing_embeddings=0
cache_hits=1 api_calls=4 avg_chunk_chars=729.0
estimated_volume: chars=240579 approx_tokens=60144

=== Strategy comparison ===
fixed: predictable chunk windows, can split through section boundaries.
structure: semantically aligned sections, but chunk sizes are less uniform.
```

### Done

- Local ingestion for `.md`, `.txt`, `.py`, `.pdf`.
- Fixed-size chunking.
- Structure-aware chunking.
- Stable chunk IDs.
- OpenAI embeddings with batch calls and retry.
- SQLite persistence.
- Embedding cache.
- `--dry-run` and `--limit` (`--dry-run` does not touch SQLite).
- Strategy comparison CLI.
- Tests and ruff validation.

### Not Done

- No FAISS.
- No hybrid search.
- No Ollama embedding provider yet.

Day 21 only needs the local document index with embeddings and metadata.

---

## Day 22 — First RAG Query

### Goal

Build the first QA flow with two modes:

- `plain`: question goes directly to LLM, no retrieved context.
- `rag`: question -> retrieve relevant chunks from SQLite -> build context -> LLM answer.

Also ship a 10-question control set and compare quality (`plain` vs `rag`).

### Retrieval Rules

- Retrieval uses the latest indexed run for `(strategy, source_root)`.
- Query embedding model is taken from that run (`index_runs.embedding_model`) to avoid mismatch.
- Similarity uses cosine over stored `embedding_json`.
- If query/chunk dimensions mismatch, fail with a clear rebuild message.

### Provider Notes

- Generation provider (`--provider`) and embedding provider are independent.
- Retrieval embedding still needs OpenAI-compatible embeddings.
- If generation is Groq and retrieval is OpenAI embeddings, both keys may be needed.

### Run (bash)

Interactive mode: run without `--question`, then type questions live (empty line / `exit` to stop).
Each question prints `plain` vs `rag` with citations:

```bash
uv run python -m week_05.main ask --mode both --provider "GPT-4o mini" --source "week_05/corpus" --strategy structure --top-k 5
```

One-shot mode: pass `--question` to answer a single question and exit:

```bash
uv run python -m week_05.main ask --mode both --provider "GPT-4o mini" --source "week_05/corpus" --strategy structure --top-k 5 --question "Что такое top_p?"
```

Run the full 10-question evaluation (reads `week_05/eval/questions.json`, runs all 10 at once):

```bash
uv run python -m week_05.main eval --provider "GPT-4o mini" --source "week_05/corpus"
```

### Control Questions Dataset

The control set lives in `week_05/eval/questions.json`.

Fields:

- `question` — the user question sent to both modes.
- `expected` — keywords/facts expected in a good answer.
- `expected_sources` — source files retrieval should cite when applicable.

`expected` and `expected_sources` are used only by `eval` after generation. They are not passed
to the LLM in either `plain` or `rag` mode.

Metrics:

- `keyword_recall_plain` / `keyword_recall_rag` — fraction of `expected` keywords found in the answer.
- `source_hit` — RAG-only check that at least one citation matches `expected_sources`.
- `retrieved_count` — number of chunks added to the RAG context (`top-k` cap).
- `avg_retrieval_score` — average cosine similarity for retrieved chunks.

`week_05/eval/results.json` is generated by `eval` and can be overwritten before the video.

### What To Verify

- `ask` without `--question` opens an interactive prompt and answers each typed question.
- `ask --mode both` prints both answers and shows retrieval summary for RAG.
- RAG output includes citations with `chunk_id`, `source`, `section`, `score`.
- `eval` prints per-question metrics and aggregate metrics.
- `eval` writes JSON report to `week_05/eval/results.json`.
- Full demo run shows `questions_run=10` and `questions_total=10`.

### Troubleshooting

- `Missing env var: OPENAI_API_KEY` during RAG retrieval -> add OpenAI key (embeddings).
- `Missing env var: GROQ_API_KEY` (or DeepSeek key) during generation -> add chosen provider key.
- `No index run found for strategy/source` -> run Day 21 `index`/`compare` first.
- `Embedding dimension mismatch` -> rebuild index with the same embedding model.
- `No relevant context found for selected strategy/run.` -> retrieval returned no chunks/top_k=0.

### Example Output

```text
Ask mode=both provider=GPT-4o mini strategy=structure top_k=5 source=week_05/corpus
Interactive mode. Type a question, empty line or 'exit'/'quit' to stop.

question> Что такое top_p?

[plain] model=gpt-4o-mini latency_s=1.14
...plain answer...

[rag] model=gpt-4o-mini latency_s=1.26
...rag answer...
retrieval: run_id=structure-... model=text-embedding-3-small retrieved=5 avg_score=0.3700
citations:
  - 9f3a... source=week_05/corpus/lecture-05-notes.md section=heading:RAG score=0.3928

question> exit
```

```text
Eval provider=GPT-4o mini strategy=structure questions=10/10
summary: plain_kw=0.420 rag_kw=0.710 rag_source_hit=0.800
```

Day 22 keyword recall is a coarse heuristic (keyword overlap), not semantic grading.

---

## Day 23 — Reranking and Filtering

### Goal

Improve RAG retrieval quality with a second-stage filter/rerank step plus query rewrite, then
compare baseline vs improved quality.

### Architecture

- Agent orchestration: `week_05/agent.py` with modes `plain` / `rag` / `both`.
- Retrieval stage 1 (`top_k_before`): broad recall from SQLite cosine search.
- Retrieval stage 2:
  - threshold filter (`min_similarity`)
  - optional MMR diversity (`--use-mmr`)
  - final `top_k` for prompt context
- Optional query rewrite (`--rewrite-query`) using the same generation provider as `--provider`.

### Run (bash)

Baseline Day 22-like run:

```bash
uv run python -m week_05.main ask --mode rag --provider "GPT-4o mini" --source "week_05/corpus" --strategy structure --top-k 5 --question "Что такое context management?"
```

Improved Day 23 run (rewrite + threshold + mmr):

```bash
uv run python -m week_05.main ask --mode rag --provider "GPT-4o mini" --source "week_05/corpus" --strategy structure --top-k 5 --top-k-before 20 --min-similarity 0.45 --use-mmr --rewrite-query --question "Что такое context management?"
```

Improved Day 23 interactive run with runtime toggles:

```bash
uv run python -m week_05.main ask --mode rag --provider "GPT-4o mini" --source "week_05/corpus" --strategy structure 
```

Inside interactive mode:

```text
:help
:top-k-before 20
:min-similarity 0.35
:mmr on
:rewrite on
Что такое context management?
```

Compare baseline vs improved on the same dataset:

```bash
uv run python -m week_05.main eval --provider "GPT-4o mini" --source "week_05/corpus" --strategy structure --top-k 5 --top-k-before 20 --min-similarity 0.45 --use-mmr --compare
```

### What To Verify

- `ask` goes through `agent.py` modes (`plain` / `rag` / `both`) and keeps Day 22 defaults.
- Interactive `ask` supports runtime commands (`:help`, `:show`, `:mode`, `:top-k`,
  `:top-k-before`, `:min-similarity`, `:mmr`, `:rewrite`, `:provider`, `:strategy`, `:reset`)
  without restart.
- RAG output prints diagnostics:
  - `before`
  - `after_threshold`
  - `final`
  - `avg_score`
  - `rewritten_query` (when rewrite enabled)
- `eval --compare` prints profile summary for `baseline` and `improved`.
- Default behavior with no new flags remains Day 22-compatible.

### Troubleshooting

- Rewrite enabled but no `rewritten_query` shown -> check `--rewrite-query` flag and provider key.
- `improved` profile not better than `baseline` -> tune `--min-similarity` (start at `0.30-0.40`)
  and/or reduce `--top-k`.
- Too few final chunks -> lower threshold or disable MMR for the run.

### Demo flow (short)

1. Run baseline `ask --mode rag` and show retrieval counts/sources.
2. Run improved `ask --mode rag` with Day 23 flags and show count reduction + rewritten query.
3. Run `eval --compare` and show profile-level quality numbers.

---

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 21 | Local document indexing pipeline: ingestion (`md/txt/py/pdf`), fixed + structure chunking, embeddings, SQLite index, metadata, strategy comparison | `-m week_05.main compare --source "week_05/corpus"`, `-m week_05.main --db "data/week_05/rag_index.sqlite" stats` | `documents.py`, `chunking.py`, `embeddings.py`, `index_store.py`, `indexer.py`, `cli.py`, `main.py` | done | _link_ |
| 22 | First RAG query: plain vs rag, SQLite retrieval, citations, 10-question control eval | `-m week_05.main ask --mode both --source "week_05/corpus" --question "..."`, `-m week_05.main eval --source "week_05/corpus"` | `retrieval.py`, `rag_qa.py`, `eval.py`, `eval/questions.json`, `cli.py`, `tests/test_retrieval.py`, `tests/test_rag_qa_eval.py` | done | _link_ |
| 23 | Reranking/filtering + query rewrite + baseline vs improved comparison | `-m week_05.main ask --mode rag --top-k-before 20 --min-similarity 0.35 --use-mmr --rewrite-query --question "..."`, `-m week_05.main eval --compare` | `agent.py`, `retrieval.py`, `rag_qa.py`, `eval.py`, `cli.py`, `tests/test_retrieval.py`, `tests/test_rag_qa_eval.py` | done | _link_ |
