# Week 05 — RAG / Document Indexing

## Structure

```text
week_05/
├── main.py                     # entrypoint: uv run python -m week_05.main
├── cli.py                      # commands: index / compare / stats
├── models.py                   # Document, Chunk, EmbeddedChunk, IndexRun, stats dataclasses
├── documents.py                # file ingestion: md/txt/py/pdf -> plain text documents
├── chunking.py                 # fixed-size and structure-aware chunking strategies
├── embeddings.py               # OpenAI embedding provider + retry helpers
├── index_store.py              # SQLite schema + run/chunk/cache persistence
├── indexer.py                  # pipeline orchestration: load -> chunk -> embed -> store
└── tests/
    ├── test_chunking.py
    └── test_store_and_indexer.py
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

For real embedding calls, put an OpenAI key in local `.env`:

```bash
OPENAI_API_KEY=...
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
uv run python -m week_05.main compare --source ".cursor/docs" --model text-embedding-3-large
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

Dry run first: no API calls, only load/chunk/count.

```bash
uv run python -m week_05.main compare --source ".cursor/docs" --dry-run
```

Real indexing with default OpenAI embeddings:

```bash
uv run python -m week_05.main index --source ".cursor/docs" --strategy fixed
uv run python -m week_05.main index --source ".cursor/docs" --strategy structure
```

Run both strategies and compare:

```bash
uv run python -m week_05.main compare --source ".cursor/docs"
```

Use the stronger OpenAI embedding model:

```bash
uv run python -m week_05.main compare --source ".cursor/docs" --model text-embedding-3-large
```

Cheap test run:

```bash
uv run python -m week_05.main compare --source ".cursor/docs" --limit 120
```

Index a folder containing a PDF:

```bash
uv run python -m week_05.main compare --source "C:/path/to/folder_with_pdf_and_docs"
```

Print DB stats:

```bash
uv run python -m week_05.main stats --db "data/week_05/rag_index.sqlite"
```

### What To Verify

- `documents=N` is non-zero.
- `chunks=N` is non-zero for both strategies.
- `missing_embeddings=0` on a healthy real run.
- `cache_hits` increases on repeated runs with the same model/text.
- SQLite DB exists at `data/week_05/rag_index.sqlite`.
- A PDF source appears in output when the source folder includes `.pdf`.
- Fixed and structure strategies produce different chunk counts/average lengths.

### Troubleshooting

- `Missing env var: OPENAI_API_KEY` -> add `OPENAI_API_KEY` to local `.env`.
- `Skipping unreadable file ...` -> file is broken or wrong encoding; fix source file and rerun.
- `missing_embeddings > 0` -> transient provider/API issue; rerun command (cache will reuse finished
  chunks).
- `chunks=0` -> source path has no supported non-empty files (`.md`, `.txt`, `.py`, `.pdf`).

### Example Output

Dry-run shape:

```text
Comparing strategies for source=.cursor/docs dry_run=True limit=60

[fixed] run_id=fixed-...
documents=7 chunks=60 missing_embeddings=0
cache_hits=0 api_calls=0 avg_chunk_chars=1197.3
estimated_volume: chars=23946 approx_tokens=5986

[structure] run_id=structure-...
documents=7 chunks=60 missing_embeddings=0
cache_hits=0 api_calls=0 avg_chunk_chars=690.5
estimated_volume: chars=13811 approx_tokens=3452

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
- `--dry-run` and `--limit`.
- Strategy comparison CLI.
- Tests and ruff validation.

### Not Done

- No answer generation.
- No chat agent.
- No FAISS.
- No reranking.
- No hybrid search.
- No Ollama embedding provider yet.

Day 21 only needs the local document index with embeddings and metadata.

---

## Progress

| Day | Task | Commands | Code | Status | Video |
|-----|------|----------|------|--------|-------|
| 21 | Local document indexing pipeline: ingestion (`md/txt/py/pdf`), fixed + structure chunking, embeddings, SQLite index, metadata, strategy comparison | `-m week_05.main index --source "...\" --strategy fixed\|structure`, `-m week_05.main compare --source "...\" [--dry-run] [--limit N] [--model ...]`, `-m week_05.main stats --db ...` | `documents.py`, `chunking.py`, `embeddings.py`, `index_store.py`, `indexer.py`, `cli.py`, `main.py` | done | _link_ |
