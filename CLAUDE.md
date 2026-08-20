# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An internal retrieval assistant (RAG chatbot) that answers questions about HBL's
policy and SOP documents — AML/CFT/KYC, sanctions, whistleblowing, data privacy,
insider trading, BCP and similar. Roughly 22 PDFs, ~1,300 pages, a mix of digital
and scanned, table-heavy.

**The frontend is built. The backend does not exist yet.** A new session picking
this up is almost certainly here to build the backend.

The full ten-phase plan lives in `docs/build-plan.html` — open it in a browser
rather than reading the raw HTML. It carries the reasoning behind everything
summarised below.

## Hard constraints

These are settled. Do not propose alternatives.

1. **Fully offline. No cloud APIs, ever.** The documents are confidential bank
   policies. No Claude API, no OpenAI, no Voyage, no Cohere, no hosted endpoint —
   not even for a one-off ingestion job. Every model runs locally.
2. **Two machines.** Code is written on a CPU-only Windows laptop and executed on
   an office workstation with an **RTX 4060 Ti, 16 GB VRAM**. Therefore: no
   absolute paths, no machine-specific assumptions, every model name in `.env`,
   and a headless CLI for every heavy operation so ingestion can run on the GPU
   box without a browser. Transfer is `git pull` + install, never manual copying.
   Do not try to benchmark or run models on the dev laptop.
3. **Never commit documents or anything derived from them.** Parsed markdown,
   rasterised page images and the vector index all contain the same confidential
   content as the PDFs. `.gitignore` already covers this; keep it that way.

## Commands

Windows paths contain spaces — quote them.

```bash
# Frontend (from frontend/)
npm install
npm run dev              # http://localhost:5173
npm run build
npx tsc --noEmit         # type-check; there is no lint or test runner yet

# Python (venv is Python 3.13.5 at ./venv, currently only pip + pillow)
./venv/Scripts/python.exe -m pip install <pkg>     # Windows
python brand/make_icons.py                          # regenerate app icons
```

The frontend has one route beyond the app itself: `/#/states`, an interaction-states
and motion reference used for design handoff. It is not part of the product.

## Decisions already made

Re-opening these wastes time; the reasoning is in `docs/build-plan.html`.

| Area | Decision |
| --- | --- |
| Framework | **No LangChain, no LlamaIndex.** Call libraries directly. LangChain's `BM25Retriever` is in-memory with no deletion, which is actively wrong for the add/delete requirement. |
| Python | **3.13** on the dev laptop. (The plan argues for 3.12 because of PaddleOCR; the user chose 3.13 and accepted losing that one OCR candidate.) |
| PDF access | PyMuPDF |
| OCR | Undecided — Phase 01 runs a bench-off of Docling / MinerU / Surya / a local VLM on five real pages. Chosen on output, not benchmarks. |
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

## Backend architecture (to build)

Start at Phase 00 in the plan: repo skeleton, `pydantic-settings` config driven by
`.env`, structured logging, a CLI entry point, and four provider protocols —
`LLM`, `Embedder`, `Reranker`, `OCR` — that every later phase codes against. Local
model choice changes often, so those interfaces matter even though there is no
cloud fallback.

Three subsystems over shared storage:

- **Ingestion** — offline, slow, runs headless on the GPU box. Per-*page* routing
  (never per-file): a page is classified DIGITAL / SCANNED / HYBRID from character
  yield, raster coverage and a garble score. HYBRID extracts the text layer *and*
  OCRs the raster regions, then merges with fuzzy overlap detection. Output is one
  human-readable markdown file per document plus per-page provenance — that file
  is the quality gate.
- **Retrieval** — dense top-30 + BM25 top-30 → RRF fusion → cross-encoder rerank →
  top-8. Hybrid is not optional: the corpus is full of exact identifiers
  (`A-INST-2025-01`, CDD, EDD, STR, PEP, thresholds) that dense search alone misses.
- **Generation** — strict grounding, citations, refusal when retrieval is thin.

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

## Open questions

- **Can the GPU workstation reach the internet** to download model weights, or is
  it air-gapped and needs them carried across? Blocking before Phase 01.
- Language of the documents is assumed English throughout.
- Authentication and chat history persistence are deferred — the user explicitly
  deprioritised sign-in until the core works.

## Repository layout

```
frontend/     the app — built and working, mock data
brand/        logo source + make_icons.py (regenerates all app icons)
docs/         build-plan.html — the ten-phase plan and all reasoning
venv/         Python 3.13 virtualenv
Design System for HBL RAG Chatbot/   Figma export, kept as visual reference only;
                                     not imported by the app
```
