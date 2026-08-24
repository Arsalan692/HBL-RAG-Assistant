# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An internal retrieval assistant (RAG chatbot) that answers questions about HBL's
policy and SOP documents — AML/CFT/KYC, sanctions, whistleblowing, data privacy,
insider trading, BCP and similar.

**The corpus is present**, in `data/documents/` (gitignored). Measured, not
estimated: **20 files, 19 unique, 519 pages**. `app.cli classify` routes them
265 digital / 236 scanned / 18 blank — so **47% of indexable pages need OCR**,
and per-page routing is doing real work: `Whistleblowing Policy & Program-2024`
alone splits 11 digital / 7 scanned, while `AFPAD 2025` is 26 scanned pages and
`Global AML CFT CPF and KYC Policy - 2023` is 49 digital ones.

**The frontend is built. Phase 00 and the Phase 01 router are done.**
`backend/` holds configuration, logging, a headless CLI, the four provider
protocols, and the per-page classifier. Nothing extracts, embeds, retrieves or
answers yet. A session picking this up is here to run the **OCR bench-off** —
the five comparison pages are already chosen, see below. Read
`backend/README.md` first.

The full ten-phase plan lives in `docs/build-plan.html` — open it in a browser
rather than reading the raw HTML. It carries the reasoning behind everything
summarised below.

## Hard constraints

These are settled. Do not propose alternatives.

1. **Fully offline. No cloud APIs, ever.** The documents are confidential bank
   policies. No Claude API, no OpenAI, no Voyage, no Cohere, no hosted endpoint —
   not even for a one-off ingestion job. Every model runs locally.
2. **Two machines.** Code is written on a CPU-only Windows laptop (8 cores) and
   the heavy work runs on an office workstation with an **RTX 4060 Ti, 16 GB
   VRAM**. Therefore: no absolute paths, no machine-specific assumptions, every
   model name in `.env`, and a headless CLI for every heavy operation so
   ingestion can run on the GPU box without a browser. Transfer is `git pull` +
   install, never manual copying.

   The laptop *can* run the pipeline — page routing, extraction, embedding the
   corpus (~30–60 min once), and OCR of a handful of pages. What it cannot do is
   bulk OCR or interactive-speed generation. Build and validate here; run the
   real ingest there.
3. **Never commit documents or anything derived from them.** Parsed markdown,
   rasterised page images and the vector index all contain the same confidential
   content as the PDFs. `.gitignore` already covers this; keep it that way.
4. **No Google Colab, and no remote GPU.** Asked and settled on 2026-08-21: the
   corpus does not go to a third party *for compute*. No uploading pages to a
   hosted OCR service, no rented GPU, no cloud inference in the pipeline.

   **Reading documents in a Claude Code session is explicitly allowed** — the
   user granted this on 2026-08-21 so OCR output can be judged against the
   actual page, which is the whole point of the bench-off and cannot be done
   from aggregate numbers. Open the PDFs and the rendered PNGs when the task
   needs it. Still do not paste bulk document text around gratuitously: read
   what the question requires, quote sparingly in replies, and prefer
   aggregates when they answer the question just as well.

## Commands

Windows paths contain spaces — quote them.

```bash
# Frontend (from frontend/)
npm install
npm run dev              # http://localhost:5173
npm run build
npx tsc --noEmit         # type-check; there is no lint or test runner yet

# Backend (venv is Python 3.13.5 at ./venv; install once with the line below)
./venv/Scripts/python.exe -m pip install -e "backend[dev]"
./venv/Scripts/python.exe -m app.cli health        # config + provider per interface
./venv/Scripts/python.exe -m app.cli health --probe  # ...and contact Ollama
./venv/Scripts/python.exe -m app.cli providers     # what's registered, what's installed
./venv/Scripts/python.exe -m app.cli paths --create
./venv/Scripts/python.exe -m app.cli classify              # route every page, corpus-wide
./venv/Scripts/python.exe -m app.cli classify --explain    # per-page numbers and reasoning
./venv/Scripts/python.exe -m app.cli classify --pick-bench # choose the OCR comparison pages
./venv/Scripts/python.exe -m app.cli bench                 # run the OCR engines over those pages
./venv/Scripts/python.exe -m app.cli extract               # the ingest pass (needs the GPU)
./venv/Scripts/python.exe -m app.cli extract --no-ocr      # digital pages only, laptop-safe
./venv/Scripts/python.exe -m app.cli verify                # audit the extraction
./venv/Scripts/python.exe -m app.cli chunk                 # 901 chunks with breadcrumbs + vintage
./venv/Scripts/python.exe -m app.cli index                 # embed into Qdrant + registry (needs bge-m3)
./venv/Scripts/python.exe -m app.cli index --embedder hashing   # dev stand-in, no weights
./venv/Scripts/python.exe -m app.cli documents             # what is indexed
./venv/Scripts/python.exe -m app.cli delete <doc_id> --yes # remove from both stores and disk
./venv/Scripts/python.exe -m pytest backend        # 163 tests, no models, corpus or engines needed

python brand/make_icons.py                          # regenerate app icons
```

The CLI works from any directory once installed, and also as `hbl health`.
Results go to stdout, logs to stderr, so `--json` output stays pipeable.

The frontend has one route beyond the app itself: `/#/states`, an interaction-states
and motion reference used for design handoff. It is not part of the product.

## Decisions already made

Re-opening these wastes time; the reasoning is in `docs/build-plan.html`.

| Area | Decision |
| --- | --- |
| Framework | **No LangChain, no LlamaIndex.** Call libraries directly. LangChain's `BM25Retriever` is in-memory with no deletion, which is actively wrong for the add/delete requirement. |
| Python | **3.13** on the dev laptop. (The plan argues for 3.12 because of PaddleOCR; the user chose 3.13 and accepted losing that one OCR candidate.) |
| PDF access | PyMuPDF |
| OCR | **`qwen2.5vl:7b` via Ollama**, settled 2026-08-21 on five real pages. Docling / MinerU / Surya were never needed. See below. |
| Embeddings | `BAAI/bge-m3` |
| Reranker | `BAAI/bge-reranker-v2-m3` |
| Keyword search | SQLite **FTS5** (BM25), in the same DB as the document registry, so deleting a document removes its vectors, keyword index and registry row in one transaction |
| Vector store | **Qdrant, embedded/local mode** — no Docker needed to develop |
| Generation | Qwen3-14B, 4-bit, served by **Ollama** |
| API | FastAPI + SSE streaming |
| Frontend | Vite + React 18 + Tailwind v4, Radix primitives directly |

**VRAM budget** — all three models are resident at once: LLM ~9 GB + ~2 GB KV
cache, bge-m3 ~2.3 GB, reranker ~2.3 GB ≈ 15.6 GB of 16 GB. If it OOMs: quantise
the two small models to 8-bit first; only drop to an 8B LLM as a last resort.

## Backend architecture

Phase 00 exists. `backend/README.md` explains it; the parts worth knowing before
writing anything:

- **`app/config.py` is the only module that reads the environment.** Anything
  else takes `Settings` as an argument. Relative paths anchor to the repository
  root, not the cwd. `HBL_LLM_BASE_URL` is validated to be loopback or LAN — a
  public host raises `ConfigError`, so a typo cannot leak the corpus.
- **The registry describes providers rather than holding them.** It stores an
  import target plus required module names and checks them with
  `importlib.util.find_spec`, so `health` runs on the laptop where torch will
  never be installed. A spec with a `phase` is a declaration; loading it fails
  naming the phase instead of raising ImportError for a module nobody wrote.
  There's a test asserting status never imports an implementation — keep it.
- **Only the LLM provider is real** (`providers/llm/ollama.py`, stdlib urllib,
  NDJSON streaming). Embedder lands in Phase 03, reranker in 04, OCR in 01.

Three subsystems over shared storage:

- **Ingestion** — offline, slow, runs headless on the GPU box. Per-*page* routing
  (never per-file) is **built**, in `app/ingest/`. HYBRID extracts the text layer
  *and* OCRs the raster regions, then merges with fuzzy overlap detection. Output
  is one human-readable markdown file per document plus per-page provenance —
  that file is the quality gate. Extraction itself is not written yet.
- **Retrieval** — dense top-30 + BM25 top-30 → RRF fusion → cross-encoder rerank →
  top-8. Hybrid is not optional: the corpus is full of exact identifiers
  (`A-INST-2025-01`, CDD, EDD, STR, PEP, thresholds) that dense search alone misses.
- **Generation** — strict grounding, citations, refusal when retrieval is thin.

### What the router learned from the real corpus

Three things that were not obvious and are easy to reintroduce:

1. **A full-page raster beats any text layer.** ~220 pages are scans that arrived
   with someone else's OCR already embedded. That text often measures perfectly
   healthy — no control characters, normal word shapes — while being wrong; one
   page renders the HBL logo as `MBL HA.aH3GANK`. So the rule is: if one image
   covers ≥60% of the page, the image *is* the page and gets re-read. The prior
   text is kept as `PageVerdict.has_prior_text` for diffing, never as the source.
   `HBL_INGEST_TRUST_PRIOR_OCR` can flip this; it should stay off.
2. **Ignore rasters too small to hold content.** Several documents are Word
   exports that place a **2×2-pixel** image behind every line of text as a
   highlight fill. Stretched to line width they read as ~57% raster coverage and
   sent every clean digital page to OCR. `signals._MIN_RASTER_PIXELS` filters them.
3. **Character density is ~30/in², not hundreds.** A4 is 96.7 in² and a full page
   of body prose is ~2,800 characters. The first threshold set was 55 and
   classified all 519 pages as scanned. Distribution is bimodal — p25 1.2,
   median 24.5, p75 33.0 — so the cutoff belongs in the gap, at 12.

There are effectively **no HYBRID pages** in this corpus: of 203 pages with a
partial raster, 193 are the header logo at 1–2% coverage. The branch stays for
uploaded documents, but do not expect it to fire on what is there today.

**Corpus hazard to handle explicitly:** several policies exist in more than one
vintage (AML/KYC and Sanctions each appear as 2023 and 2025), plus byte-identical
duplicates. Untreated, the retriever returns a superseded clause and the model
states it confidently. Treatment: SHA-256 dedupe at ingest, `policy_family` +
`year` metadata, prefer newest, and surface genuine conflicts rather than
silently resolving them.

## Frontend contract the backend must satisfy

The frontend is complete and running against mock data. Two files define the
contract:

- **`frontend/src/types.ts`** — `Source`, `Message`, `ChatSummary`. These mirror
  what the API should return; match them and no component needs changing.
- **`frontend/src/data/mock.ts`** — the canned content to replace. Everything the
  UI renders comes from here.

Non-obvious details:

- **Answers are markdown**, and inline citations are written as literal `[1]`,
  `[2]` in the text. `components/chat/Markdown.tsx` swaps those tokens for
  clickable pills at render time. The model prompt must emit that exact form.
- Tables are expected and styled; GFM table syntax works.
- Streaming state is `StreamingState` in `components/chat/Thread.tsx`. The
  retrieval stepper wants `step`, `documentCount` and `sourceCount`, and sources
  arrive *before* the answer text so citation pills resolve while streaming.
- The simulated stream lives in `frontend/src/App.tsx` (`send`, `STEP_DELAYS`).
  Replace it with a real SSE reader; the component tree does not change.

Endpoints in the plan: `POST /chat` (SSE), `POST /documents` (upload → job id),
`GET /documents` (list + ingest status), `DELETE /documents/{id}`, a page-image
endpoint for citation previews, `GET /health`.

## Frontend conventions

Only relevant if touching the UI.

- **Colour tokens live in `frontend/src/styles/theme.css` and nowhere else.**
  There are two teals on purpose: `--hbl-green` (#009F8C) is the true brand
  colour, used only where nothing sits on top of it — borders, focus rings,
  progress bars, the streaming caret. `--hbl-solid` is the accessible fill for
  anything carrying text or an icon, because white on the brand teal is 3.31:1.
  **Use `bg-hbl-solid` with `text-hbl-on-solid`; never `text-white` on a teal
  fill.** In dark mode the fill stays bright and the foreground goes near-black.
- **Do not use rem-based Tailwind sizes for fixed layout widths.** The root font
  size is 15px *and* user-adjustable in Settings, so `w-70` is 262px, not 280,
  and would resize the sidebar when the reader changes text size. Use explicit
  pixels (`w-[280px]`).
- Interaction-state classes are centralised in `frontend/src/lib/variants.ts` and
  shared with the `/#/states` reference page, so the two cannot drift. Add states
  there, not inline.
- Motion: one easing curve, `cubic-bezier(0.32, 0.72, 0, 1)`, durations 180–260ms.

## GPU workstation — outbound-restricted, not air-gapped

Corrected 2026-08-24, having previously been recorded here as fully air-gapped.
**The workstation can reach the internet**: `pip install` works, PyPI and
pytorch.org are reachable, libraries install directly. Hand-carrying wheels from
the laptop is no longer necessary.

The constraint that actually matters is unchanged, and it was never really about
the network — it is about direction:

- **Inbound is fine.** Downloading packages and model weights onto that machine
  is ordinary work. Do it there rather than staging a transfer.
- **Outbound is not.** No document, no page image, no parsed markdown and no
  chunk may leave. No hosted OCR, no cloud embedding, no remote inference of any
  kind. `_require_local_url` in `config.py` enforces this at the one place a
  model endpoint enters the system, and stays.

Consequences for how code is written — most of these survive the correction,
because they were good practice rather than air-gap workarounds:

- **Model names in `.env` may be repo ids again** where a download is wanted.
  Local folder paths still work and are still preferable for anything already
  staged, since they cannot silently re-download.
- `HBL_HF_OFFLINE=true` is now a *choice*, not a necessity. Keep it on: it means
  weights are fetched deliberately, once, by a command someone ran — never as a
  side effect of a library call during an ingest run.
- `docling`, MinerU and `surya` fetching their own weights at first run is no
  longer a blocker. It stays undesirable — a run that pauses to download is a
  run whose timings mean nothing.
- **`qwen2.5vl:7b` and `bge-m3` are already pulled there.** Ollama works, but
  note the embedding endpoint may not: see below.

### The workstation is re-cloned, never pulled

`git pull` is not available there. Each time, the repository is cloned fresh and
the previous copy deleted. Everything gitignored therefore **dies with the old
clone** — and one of those things is expensive:

| Lost on re-clone | Cost to rebuild |
| --- | --- |
| `data/parsed/` | **~55 minutes of GPU extraction** |
| `storage/qdrant/`, `registry.sqlite` | a full re-index |
| `data/documents/` | re-copying the 20 PDFs by hand |
| `backend/.env` | retyping the configuration |

So **keep the durable artefacts outside the working copy.** Both roots accept an
absolute path, and set as Windows *user environment variables* they survive the
clone that would otherwise take the `.env` with it:

```
setx HBL_DATA_DIR     "D:\hbl-data"
setx HBL_STORAGE_DIR  "D:\hbl-storage"
```

A fresh clone then needs only:

```bash
pip install -e backend
hbl health          # paths should point outside the clone
```

and the corpus, the extracted markdown and the index are all still there.

When adding anything durable, put it under one of those two roots rather than
beside the code. A file written into the repository is a file that exists until
the next clone.

### The Ollama embedding endpoint may be disabled

There are two routes to bge-m3 and they are interchangeable behind the
`Embedder` protocol, so choosing between them is one line in `.env`:

| `HBL_EMBEDDING_PROVIDER` | How | Needs |
| --- | --- | --- |
| `ollama` | HTTP to the Ollama already running | nothing — stdlib urllib |
| `bge-m3` | sentence-transformers, in-process | torch + weights (~4.6 GB) |

Prefer `ollama` — but **check it first**. The laptop's Ollama answers
`501 This server does not support embeddings`, which is llama.cpp phrasing
rather than `ollama serve`, so the build there has the endpoint off. If the
workstation does the same, the in-process route is the only one available.

```bash
curl http://127.0.0.1:11434/api/embed -d '{"model":"bge-m3","input":"test"}'
```

An array of numbers means `ollama` works. A 501 means use `bge-m3`.
`hbl health --probe` reports which case you are in and names the fix.

**Phase 04 needs torch regardless.** The reranker is a cross-encoder and Ollama
has no rerank endpoint, so `pip install torch sentence-transformers` on the
workstation is wanted either way — the Ollama route only defers it.

## Answering speed is a requirement

The user asked for it to feel like a normal chatbot. The 4060 Ti has 288 GB/s of
bandwidth, so this is a real constraint, and the lever is *time to first token*,
not tokens per second.

- **`HBL_LLM_THINK=false` is the default and must stay off.** Qwen3 emits a
  `<think>` block before answering — hundreds of unseen tokens ahead of the first
  visible word. Largest single win, costs nothing.
- **Both `qwen3:8b` and `qwen3:14b` are being carried across** to be benched
  against each other. ~35–45 tok/s vs ~20–25. Expect 8B to win; the task is
  grounded summarising, not open-ended reasoning. Don't assume 14B.
- Prefill dominates: 8 chunks ≈ 3–4k tokens read before a word is written.
  `HBL_RETRIEVAL_RERANK_CANDIDATES` (60 → 30) and `RERANK_TOP_K` are the knobs.

## The OCR bench-off — run, decided, done

`hbl bench` ran all three vision models over five representative pages on the
RTX 4060 Ti (2026-08-21). Winner: **`qwen2.5vl:7b`**, already set as the
default in `config.py`. Docling, MinerU and Surya were never needed, so nothing
had to be staged on the workstation.

The pages were picked by measurement (`classify --pick-bench`), one per
category, across five documents. Re-run it if the corpus changes:

| Category | Document | Page |
| --- | --- | --- |
| clean digital | `A-INST-2025-01- Encl. Global AML CFT CPF and KYC Policy (1).pdf` | 7 |
| full scan | `AFPAD - Frequently Asked Questions (FAQs) (1).pdf` | 1 |
| mixed | `AFPAD 2025.pdf` | 3 |
| dense table | `Financial Crime Country Risk Guidelines.pdf` | 10 |
| poor scan | `Compliance Assurance Program 2023.pdf` | 1 |

**What decided it was one page** — the dense table, an 8-row ruled table of
country risk classifications. All three produced a well-formed markdown table.
Only one produced the *right* one:

- **`qwen2.5vl:7b`** — all 8 rows correct, including the cell holding two
  values (`Israel (Unacceptable)` / `India (Restricted)`). Also recovered the
  Urdu in the letterhead. ~14s/page. **Chosen.**
- **`qwen2.5vl:3b`** — corrupted cells silently. Shifted row 3 so the
  Exclusions value `No` vanished, and deleted row 5's entire Exclusions
  sentence, leaving `Unacceptable` in its place. Fluent, well-formed, wrong.
- **`glm-ocr:latest`** — read the table correctly and fastest, but fell into a
  repetition loop on a sparse title page, emitting the same four lines **115
  times** until it hit the token ceiling. This corpus is full of sparse pages.

This is why the harness reports no score and picks no winner: all three scored
identically on characters and table count. The 3B failure is invisible to every
automatic metric and obvious to a person reading two columns side by side.

**Two defects in 7B are handled in `providers/ocr/vlm.py`**, not left to the
model: it wraps output in a ```` ```markdown ```` fence (stripped by `_unfence`,
which only removes a fence enclosing the *whole* response, since these documents
quote real code blocks), and it will impose table structure on a title page (the
prompt now says a heading block is not a table). `_degenerate_repeat` flags the
glm-ocr-style loop as a warning if any engine ever does it again.

The bench-off also settled a design question with evidence. On `AFPAD 2025` p.3
the embedded prior OCR layer reads `HBL HAl-3:laBANK  1. Introduction
Agenda 5.2.3 ...` — garbled letterhead, raw control bytes, **and scrambled
reading order**. Re-reading the raster fixed all three. Keep
`HBL_INGEST_TRUST_PRIOR_OCR=false`.

## Open questions

- Language of the documents is assumed English throughout.
- Authentication and chat history persistence are deferred — the user explicitly
  deprioritised sign-in until the core works.

## Repository layout

```
backend/      config, logging, CLI, provider protocols, per-page router. See its README.
              app/ingest/     signals (measure) → router (decide) → render → bench (pick) → benchmark (run)
              app/providers/ocr/  vlm.py (Ollama vision, real) + docling.py (adapter, needs staging)
frontend/     the app — built and working, mock data
brand/        logo source + make_icons.py (regenerates all app icons)
docs/         build-plan.html — the ten-phase plan and all reasoning
venv/         Python 3.13 virtualenv
data/documents/   the 20 source PDFs — gitignored, never commit
data/parsed/, data/page_images/   derived, equally confidential, equally ignored
storage/      registry DB, Qdrant index, model cache — gitignored
Design System for HBL RAG Chatbot/   Figma export, kept as visual reference only;
                                     not imported by the app
```
