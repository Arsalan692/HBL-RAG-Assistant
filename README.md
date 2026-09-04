# HBL Policy Assistant

A retrieval assistant over internal bank policy and SOP documents — AML/CFT/KYC,
sanctions, whistleblowing, data privacy, insider trading, BCP. Ask a question in
plain English, get an answer grounded in the actual clauses, with citations you
can open.

**It runs entirely on your own hardware.** No cloud APIs, no hosted inference, no
document ever leaving the machine. That is not a preference — the corpus is
confidential bank policy, and the constraint shaped every design decision below.

<p>
  <img alt="Python 3.13" src="https://img.shields.io/badge/python-3.13-3776AB?logo=python&logoColor=white">
  <img alt="React 18" src="https://img.shields.io/badge/react-18-61DAFB?logo=react&logoColor=black">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-SSE-009688?logo=fastapi&logoColor=white">
  <img alt="Ollama" src="https://img.shields.io/badge/Ollama-local-000000?logo=ollama&logoColor=white">
  <img alt="tests" src="https://img.shields.io/badge/tests-244%20passing-2ea44f">
</p>

---

## What it does

- **Answers from the documents, or not at all.** Every claim carries a citation.
  When retrieval comes back thin, the question never reaches the language model —
  there is nothing to ground an answer in, so the system refuses instead of
  improvising.
- **Hybrid retrieval.** Policy text is full of exact identifiers — `A-INST-2025-01`,
  CDD, EDD, STR, PEP, numeric thresholds — that semantic search alone reliably
  misses. Dense and keyword search run in parallel and are fused.
- **Reads scanned pages.** Roughly 47% of the corpus is scans. Each *page* is
  routed independently: text layers are read directly, images go to a local
  vision model.
- **Handles competing vintages.** Several policies exist as both a 2023 and a 2025
  edition. Superseded clauses are marked and ranked last, never silently dropped —
  where two editions disagree, that disagreement is usually the answer.
- **Add and remove documents from the interface.** Upload a PDF, watch it ingest
  page by page, delete it and every trace goes with it.

## How it works

**Ingestion** — offline, slow, run once:

```
PDFs ──► per-page router ──► extraction ──► chunking ──► index
             │                    │                        │
      digital / scanned      text layer, or           Qdrant   (dense vectors)
      decided by measured    qwen2.5vl:7b on a        SQLite FTS5 (BM25)
      page signals          rendered raster
```

**Answering** — every question:

```
question
   │
   ├─► dense search  (bge-m3)        top 30 ─┐
   └─► keyword search (BM25 / FTS5)  top 30 ─┴─► RRF fusion ─► cross-encoder rerank ─► top 8
                                                                          │
                                                    scores below threshold ├─► refuse (no model call)
                                                                          │
                                                              qwen3:8b, grounded ─► cited answer
```

Fusion is by **rank position, not score** — cosine similarity and BM25 share no
scale, so averaging them is meaningless. Reciprocal Rank Fusion sidesteps that
entirely.

## The interesting part: three bugs that passed every test

All three produced output that *succeeded* and was *wrong*. Green unit tests
either side of each one. They were found only by running real queries against the
real index, and they are the reason this repository is worth reading.

**1. The most quotable identifier in the corpus was unfindable.**
`A-INST-2025-01` is printed on a covering instruction's front page and appears in
no clause of any document. It reached the document title and stopped — so keyword
search, the half of retrieval that exists precisely to catch exact identifiers,
returned **zero** hits for it. Fixed by carrying the circular number onto every
chunk of its document in a dedicated column, weighted low enough that repeating it
across 107 chunks cannot flood the results.

**2. Reranking then threw that fix away.** The cross-encoder only ever saw raw
chunk text — no title, no identifier, no section breadcrumb — so it scored all 179
correctly-retrieved chunks below threshold and kept the wrong document anyway.
Passages are now reranked as `title · circular · section` followed by the text.
The identifier query went from **0.388 on the wrong document to 0.993 on the right
one**, with no regression on paraphrase queries.

**3. The refusal threshold was refusing answerable questions.** *"Who will approve
donations worth of 30 Million?"* returned nothing, though the policy states the
answer outright and keyword search ranked that clause first. Measured, the two
populations are far apart:

| Question | Score |
| --- | --- |
| submarine hatch bolt torque *(no answer exists)* | 0.0005 |
| sourdough at altitude *(no answer exists)* | 0.0009 |
| the donations question *(answerable)* | 0.0999 |
| checks applying to a PEP *(answerable)* | 0.2050 |

The threshold was **0.15** — sitting on the wrong side of a 100× gap, rejecting
phrasing rather than irrelevance. It is now `0.02`: about 20× the noise floor and
5× below the weakest true positive. Measured, not guessed.

The same investigation turned up a separate defect it had not caused: a
contents-page line with dot leaders was being parsed as a section heading, so every
clause after it inherited the breadcrumb `Donation Application Form` — filing
approval thresholds under a form.

## Getting started

**Prerequisites**

- Python 3.13, Node 20+
- [Ollama](https://ollama.com) running locally
- An NVIDIA GPU for real speed. CPU works and is how this was developed — expect
  minutes per answer rather than seconds.

**Models** (all local, ~20 GB):

```bash
ollama pull qwen3:8b        # generation
ollama pull qwen2.5vl:7b    # OCR — chosen by benchmark, see below
ollama pull bge-m3          # embeddings
```

The reranker is a cross-encoder and Ollama has no rerank endpoint, so it runs
in-process via torch:

```bash
hf download BAAI/bge-reranker-v2-m3 --local-dir /path/to/bge-reranker-v2-m3
```

**Install**

```bash
git clone https://github.com/Arsalan692/HBL-RAG-Assistant.git
cd HBL-RAG-Assistant

python -m venv venv
./venv/Scripts/python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu128
./venv/Scripts/python.exe -m pip install sentence-transformers
./venv/Scripts/python.exe -m pip install -e "backend[dev]"

cd frontend && npm install && npm run build && cd ..
```

**Configure** — copy `backend/.env.example` to `backend/.env` and set what differs
from the defaults:

```ini
HBL_DEVICE=cuda
HBL_RERANKER_MODEL=/path/to/bge-reranker-v2-m3
HBL_DATA_DIR=/path/to/data
HBL_STORAGE_DIR=/path/to/storage
```

**Build the index** — put PDFs in `data/documents/`, then:

```bash
hbl classify    # route every page; confirms the corpus looks as expected
hbl extract     # the OCR pass — the slow one
hbl verify      # audit it before trusting it
hbl chunk
hbl index
```

**Run it**

```bash
hbl serve       # http://127.0.0.1:8000
```

One command, one port. The API serves the built frontend from `frontend/dist`, so
there is nothing else to start.

## Command line

Every heavy operation has a headless command, so ingestion can run on a GPU box
over SSH with no browser involved. Results go to stdout and logs to stderr, so
`--json` stays pipeable.

```bash
hbl health --probe                  # resolved config, providers, and contact Ollama
hbl classify --explain              # per-page routing with the numbers behind each verdict
hbl bench                           # compare OCR engines on representative pages
hbl extract --no-ocr                # digital pages only, no GPU needed
hbl search "what is EDD?" --text    # the retrieval pipeline, with snippets
hbl search "CDD" --no-rerank        # fusion order, to see what reranking changes
hbl ask "who approves a donation of PKR 30 million?"
hbl documents                       # what is indexed, and in what state
hbl delete <doc_id> --yes           # remove it from everywhere
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/chat` | Ask a question. SSE: steps, sources, then answer deltas. |
| `POST` | `/documents` | Upload a PDF → `202` and a job id. |
| `GET` | `/documents` | What is indexed. |
| `GET` | `/documents/jobs` | Ingest progress, per page. |
| `DELETE` | `/documents/{id}` | Remove vectors, chunks, page images and the source file. |
| `GET` | `/health` | Readiness and the resolved provider behind each interface. |

```bash
curl -sN -X POST localhost:8000/chat -H "Content-Type: application/json" \
     -d '{"question":"what is enhanced due diligence?"}'
```

Sources arrive **before** the answer text, so citation pills resolve while the
response is still streaming.

## Design decisions worth knowing

**No LangChain, no LlamaIndex.** Libraries are called directly. LangChain's
`BM25Retriever` is in-memory with no deletion, which is actively wrong when
documents must be removable.

**The index records which embedder built it.** Every embedder here emits 1024
floats, so the vector store cannot tell a development stand-in from the real model
and will happily accept both into one collection. Nothing crashes; retrieval just
stops meaning anything. A one-row table holds a fingerprint like `bge-m3:1024`,
checked before any read or write, and a mismatch refuses to start while naming the
fix.

**Citations are verified in code, not requested in a prompt.** A prompt is a
request. A `[9]` when eight passages were supplied gets stripped from the stream
and counted. `unused_sources` is the matching diagnostic in the other direction —
consistently high means retrieval is handing over more than the answer needs, and
prefill is the largest cost in time-to-first-token.

**The OCR engine was chosen by reading pages, not by metrics.** Three vision models
ran over five representative pages. All three scored identically on characters and
table count. One of them silently corrupted cells in a ruled table — a value
vanished, another was replaced — while producing perfectly well-formed markdown.
Another looped on a sparse title page, repeating four lines 115 times. The failure
that mattered was invisible to every automatic measure and obvious to a person
reading two columns side by side.

**Memory is the binding constraint on a 16 GB machine.** The generation model, the
embedder and the reranker together do not fit alongside a browser. Models are
released between retrieval stages on CPU, the vision model is handed back when a
document finishes, and `keep_alive` is a documented tuning lever rather than a
default nobody examined. Getting this wrong produces a segfault with no exception
and no message — it happened four times, and each cause is written down.

## Layout

```
backend/
  app/
    config.py          the only module that reads the environment
    cli.py             the headless entry point
    ingest/            signals → router → render → extract → structure → chunk
    store/             registry.py (SQLite + FTS5) · vectors.py (Qdrant) · index.py
    retrieve/          fuse.py (RRF) → search.py (pipeline, refusal, vintages)
    generate/          prompt.py (grounding rules) → answer.py (events, citation audit)
    providers/         llm · embedding · reranker · ocr — one protocol each
    api/               FastAPI app, SSE chat, upload jobs
  tests/               244 tests; no models, corpus or GPU required
frontend/              Vite + React 18 + Tailwind v4 + Radix primitives
docs/build-plan.html   the ten-phase plan and the reasoning behind it
```

## Tests

```bash
./venv/Scripts/python.exe -m pytest backend
```

244 tests, and they run on a laptop with no models installed, no corpus present
and no GPU. Providers are described by import target and checked with
`importlib.util.find_spec`, so the health command works on a machine where torch
will never exist.

## A note on the data

No documents are in this repository, and none ever will be. Parsed markdown,
rasterised page images and the vector index all carry exactly the same
confidential content as the source PDFs, so `.gitignore` covers all of them —
in one case deliberately leaving a pattern unanchored, because an ingest run with
different paths had already produced a stray output directory at the repository
root.

The offline constraint is enforced at the one place a model endpoint enters the
system: `HBL_LLM_BASE_URL` is validated to resolve to loopback or the local
network, and a public host raises at startup. A typo in a config file should not
be able to send bank policy somewhere.

---

Built as an internship project at HBL. The full ten-phase plan, with the reasoning
behind every decision above, is in `docs/build-plan.html`.
