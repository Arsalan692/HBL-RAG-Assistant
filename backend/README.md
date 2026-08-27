# Backend

The offline half of the assistant. Phases 00 through 03 are done: configuration,
structured logging, a headless CLI, the four provider contracts, per-page
routing, the OCR bench-off, extraction to markdown, structure-aware chunking,
and the index with true deletion. No retrieval, generation or API yet — those
are Phases 04–06.

## Install

On the development laptop, the core dependencies are two packages and nothing
heavy:

```bash
../venv/Scripts/python.exe -m pip install -e ".[dev]"    # Windows
```

On the GPU workstation, add the models afterwards — one phase at a time, not
all at once:

```bash
pip install -r requirements.txt
pip install -r requirements-gpu.txt
```

`requirements-gpu.txt` is deliberately mostly commented out. Each block names
the phase that needs it, and the OCR entries are bench-off candidates: install
the ones being compared, delete the losers.

## Commands

```bash
python -m app.cli health              # resolved config + the provider behind each interface
python -m app.cli health --probe      # ...and actually contact Ollama
python -m app.cli health --json       # machine-readable, on stdout
python -m app.cli providers           # every registered provider, and whether it can run here
python -m app.cli paths --create      # create the data/ and storage/ directories

python -m app.cli classify            # route every page of the corpus
python -m app.cli classify --explain  # ...with the numbers behind each verdict
python -m app.cli classify --pick-bench   # nominate the OCR comparison pages
python -m app.cli classify --explain "data/documents/Some Policy.pdf"   # one file

python -m app.cli bench               # every available OCR engine over the chosen pages
python -m app.cli bench --engines vlm=qwen2.5vl:3b vlm=glm-ocr:latest
python -m app.cli bench --page "Donations Policy 2024.pdf:9" --dpi 400

python -m app.cli extract             # the real pass: markdown per document
python -m app.cli extract --no-ocr    # digital pages only, no GPU needed
python -m app.cli extract --force     # ignore the page cache and redo

python -m app.cli verify              # audit the extraction; exits 1 on real problems
python -m app.cli verify --fast       # skip the prior-OCR comparison

python -m app.cli chunk               # split parsed markdown into retrievable chunks

python -m app.cli index               # embed chunks into Qdrant + the registry
python -m app.cli index --reset       # drop the vectors first — required after changing embedder
python -m app.cli index --embedder hashing   # no weights needed; dev only
python -m app.cli documents           # what is indexed, and in what state
python -m app.cli delete <doc_id> --yes      # remove it from everywhere

python -m app.cli search "what is enhanced due diligence?"   # the whole retrieval pipeline
python -m app.cli search "A-INST-2025-01" --text             # ...with passage snippets
python -m app.cli search "CDD" --no-rerank                   # fusion order, to see what reranking changes

python -m app.cli ask "what is enhanced due diligence?"      # ...and stream a cited answer
python -m app.cli ask "..." --model qwen3:8b                 # override the generation model
```

`pip install -e .` also puts an `hbl` script on PATH, so `hbl health` works from
anywhere. Logs always go to stderr, results to stdout, so `--json` stays
pipeable however loud the log level is.

## Configuration

Everything is in `.env`; copy `.env.example` and uncomment only what you change.
Relative paths anchor to the **repository root**, not the working directory, so
the same `.env` means the same thing on both machines.

`app/config.py` is the only module that reads the environment. If something
else needs a setting, it takes `Settings` as an argument.

One rule is enforced rather than documented: `HBL_LLM_BASE_URL` must resolve to
loopback or the local network. A public host raises `ConfigError` at startup.
The corpus is confidential bank policy, and a typo in `.env` should not be able
to send it somewhere.

## Layout

```
app/
  config.py            every setting, one class per concern
  logging_config.py    console and JSON formatters, extras on both
  errors.py            the exception hierarchy
  cli.py               the headless entry point
  providers/
    base.py            LLM, Embedder, Reranker, OCR — the four protocols
    registry.py        which implementation backs each, and whether it can run
    llm/ollama.py      generation via a local Ollama server
  ingest/
    signals.py         measures a page: text density, raster coverage, garble
    router.py          decides: digital / scanned / hybrid / empty
    render.py          rasterises a page to PNG, once, for every engine alike
    bench.py           picks representative pages for the OCR comparison
    benchmark.py       runs the engines over them and writes output to compare
    extract.py         reads every page into one markdown file per document
    verify.py          audits the result for pages that succeeded but came out wrong
    metadata.py        which policy a document is, and which vintage
    structure.py       markdown back into sections, minus furniture and contents pages
    chunk.py           sections into retrievable units with breadcrumbs
    pipeline.py        runs the three over the corpus, writes chunks.jsonl
  store/
    registry.py        SQLite: documents, chunks and the FTS5 keyword index
    vectors.py         embedded Qdrant, one point per chunk
    index.py           indexing, and deletion that leaves nothing behind
  providers/embedding/
    bge_m3.py          the real embedder, 1024 dimensions, GPU
    hashing.py         DEVELOPMENT ONLY: hashed n-grams, no model
  providers/ocr/
    vlm.py             the chosen engine: a vision model served by Ollama
    docling.py         adapter kept for the record; never needed
tests/                 config, registry, routing, rendering, harness — no models,
                       no corpus, no engines needed
```

### How the bench-off works

`hbl bench` renders the chosen pages **once** and hands the identical file to
every engine — otherwise the comparison measures the renderer as much as the
reader. Output is one markdown file per engine per page, named
`<category>_p0007_<engine>.md` so the files for a single page sort together;
you read across them and decide.

It deliberately produces **no score and no winner.** The failure that matters on
this corpus is an engine flattening a table into fluent prose, and every
automatic metric rates fluent prose highly. What it does record — seconds,
characters, tables detected, engine warnings — only catches the gross failures
so nobody has to read five files to spot them.

A run never aborts. A missing package, un-staged weights or a model that was
never pulled is written into `engines_unavailable` and the next engine starts.
That matters on the air-gapped workstation, where a partial install is normal.

Engines can carry a model: `vlm=qwen2.5vl:3b` splits on the first `=`, so
Ollama's own `name:tag` colons survive. That is the comparison worth running
first — all three vision models are already pulled, and if 3B reads these pages
as well as 7B it halves the OCR pass and frees 3 GB of VRAM.

### Why routing distrusts a scan's existing text layer

About 220 pages of this corpus are scans that already carry a text layer from
somebody else's OCR. That text can measure perfectly healthy — real words, real
spacing, nothing a quality heuristic would flag — and still be wrong: one page
extracts the HBL logo as `MBL HA.aH3GANK`.

Nothing downstream can catch this. Wrong text embeds, retrieves and gets cited
exactly like right text, and the answer is confident either way. So the rule is
structural rather than statistical: **if one image covers most of the page, the
image is the page**, and the page gets re-read no matter how good its text looks.
The prior layer is kept on `PageVerdict.has_prior_text` so extraction can diff
against it — a free accuracy signal — but it is never the source.

`HBL_INGEST_TRUST_PRIOR_OCR=true` reverses this. It exists so the decision is
visible and reversible, not because it is a good idea.

### Why the registry describes providers instead of holding them

`health` has to work on the laptop, where torch is not installed and never will
be. So the registry stores an import target and a list of required modules, and
checks availability with `importlib.util.find_spec` — which answers "could this
be imported?" without importing it. Nothing heavy loads until something asks to
embed. There is a test asserting exactly this, because it is the kind of
property that quietly breaks.

A spec carrying a `phase` is a *declaration*: the name and its dependencies are
settled, the code arrives in that phase. Loading one fails with a sentence
naming the phase rather than an ImportError for a module nobody wrote.

### Why the protocols exist without a cloud fallback

Not as a route back to hosted APIs — there is no route back. A fully local
stack swaps models *more* often than a hosted one: the OCR engine is chosen by
bench-off in Phase 01, and the generation model may be re-picked if the VRAM
budget bites. Both should be a line in `.env`, not a refactor.

## What the corpus actually looks like

Measured with `classify`, not estimated: **20 files, 19 unique after SHA-256
dedupe, 519 pages** — 265 digital, 236 scanned, 18 blank. So **47% of indexable
pages need OCR**, and routing per page rather than per file matters:
`Whistleblowing Policy & Program-2024` splits 11 digital / 7 scanned inside one
document.

Scanned pages sit at 100–206 dpi, the poorest at 100. There are effectively no
true hybrids — of 203 pages with a partial raster, 193 are the header logo at
1–2% coverage.

## The OCR engine is chosen

`qwen2.5vl:7b` via Ollama, decided 2026-08-21 by running all three available
vision models over five representative pages on the RTX 4060 Ti. Docling,
MinerU and Surya were never needed — nothing had to be staged on the air-gapped
machine.

One page decided it. On an 8-row ruled table of country risk classifications,
all three engines produced a well-formed markdown table and scored identically
on characters and table count. Only `qwen2.5vl:7b` produced the *correct* one.
`qwen2.5vl:3b` shifted a column so one `No` disappeared and deleted another
cell's entire sentence; `glm-ocr` read the table well but looped on a sparse
title page, repeating four lines 115 times.

That is the case for a harness that reports no score: the 3B failure is
invisible to every automatic metric and obvious to a person reading two columns
side by side.

### Why a digital page can still need OCR

`PageVerdict.kind` says what a page *is*; `PageVerdict.strategy` says what to do
with it. They came apart on evidence. PyMuPDF finds the ruled table on
`Financial Crime Country Risk Guidelines` p.10 and then reconstructs it as
33x8 instead of 9x4, duplicating cells across columns — while the VLM read the
same table exactly. So a digital page holding a table is routed to OCR.

That is 56 of 265 digital pages, about thirteen extra minutes of GPU across the
corpus, and it is the difference between a correct table and a plausible wrong
one. The detector is used only as a signal that structure exists, never for its
reconstruction.

### Why extraction needs a separate audit

Extraction reports its own failures honestly: a page that raised is recorded as
an error and appears in the markdown as a visible marker. `verify` is for the
other kind — pages that **succeeded and are wrong anyway**. Every check exists
because the corpus produced it:

- A title page came back as `![](https://i.imgur.com/...)`. The model invented a
  URL instead of reading, and dropped the document's own title. 36 characters,
  no error, no warning — invisible to everything else.
- A page routed to OCR *because it holds a table* can come back without one.
  The router knows the table was there and the output knows it is gone; nothing
  saw both until this pass.
- A scan carrying its own prior OCR layer gives two independent readings of the
  same page. Corpus median agreement is 96%, which is cheap corroboration; the
  tail below 55% points at the pages worth looking at.

Real URLs are deliberately not flagged — these policies cite OFAC, OFSI, SECP
and the EU sanctions map, and that is content. Nor is a warning that names a
*recovery*: "first attempt returned an image placeholder; recovered on retry"
describes a page that came out fine, and matching `placeholder` as a substring
reported it as a failure.

Ingestion currently exits clean: 444 pages, no errors, twelve warnings — five
`[illegible]` markers, seven pages where our reading disagrees with the scan's
own prior OCR, all seven checked and ours the better one.

### Chunking, and the two things the corpus made hard

Splits follow section boundaries, not a character count: ~700 tokens is a
target, and a heading always ends a chunk. Tables are atomic — half a table of
country risk classifications still reads as complete, it simply omits the rows
that would have contradicted it.

**Vintage.** `Global AML CFT CPF and KYC Policy - 2023.pdf` and
`A-INST-2025-01- Encl. Global AML CFT CPF and KYC Policy.pdf` are two vintages
of one policy, near-identical in wording and different in substance. Every
chunk carries `policy_family` and `year` so retrieval can prefer the newer and
surface a genuine disagreement rather than returning whichever embedded closer.
The year comes from the filename, because the cover page often states none.

**Run-on headings.** The vision model routinely transcribes a heading and the
sentence after it onto one line:

    1.3 Risk Categories There are four risk-based categories that apply...

Nothing in that line marks where the title stops — but the contents page says
`1.3 Risk Categories 4`, so `contents_index()` reads the true titles off it and
splits the body back out. Without it the breadcrumb on every clause in the
section carries a sentence of prose, and that breadcrumb is the citation.

### What "deleted" has to mean

Two stores cannot share a transaction. SQLite holds the registry, the chunks
and the keyword index and commits all three together; Qdrant is separate. So
deletion is ordered so every failure leaves evidence rather than a document
that is half gone and looks whole:

1. mark the document `deleting` — committed, survives a crash
2. drop its vectors
3. drop its registry row, chunks and keyword entries in one transaction
4. remove its parsed markdown, sidecar and rendered page images

A crash after step 1 leaves a row saying `deleting`, which `purge_unfinished`
finds and completes on the next run. Step 4 matters as much as the rest: the
derived files carry the same confidential content as the PDF, so "deleted" has
to mean gone from disk, not merely unindexed.

### Why a hashing embedder exists

So the registry, the vector store, indexing and deletion could be built and
proven on a laptop with no GPU and no staged weights. It hashes character
n-grams into buckets — two texts sharing spelling land near each other, which
is enough for a smoke test and nothing like enough to retrieve a policy clause.
It warns on every load, because the risk is not somebody choosing it but
somebody forgetting they did.

And a warning is not enough on its own, because it scrolls past. The index
itself records which embedder built it — see below.

### Why the index carries a fingerprint

Every embedder here returns `HBL_EMBEDDING_DIMENSION` floats. Qdrant therefore
cannot tell hashed n-grams from bge-m3, and will accept both into the same
collection without complaint. Nothing crashes; the scores just stop meaning
anything, which is the hardest kind of fault to notice.

So `index_meta` holds one row — `bge-m3:1024` — and `ensure_same_embedder()`
checks it before any read or write. A mismatch is refused, with the fix in the
message. The fingerprint names the *model*, never the route or the path, so
`bge-m3` via Ollama and `D:/transfer/bge-m3` loaded in-process agree, and moving
between machines does not demand a pointless re-index.

One trap worth knowing: `VectorStore.drop()` deletes points rather than the
collection, because in embedded mode `delete_collection` followed by a recreate
under the same name **brings the old points back** — the data on disk is never
purged. The obvious implementation silently does nothing.

### Retrieval, and its two deliberate surprises

`app/retrieve/` is dense top-30 + BM25 top-30 → RRF → cross-encoder → top-8.

RRF fuses by *position*, never by score, because cosine similarity and BM25
share no scale and normalising either one lets whichever has the wider spread on
a given query dominate. With `k=60`, a chunk both retrievers rank second beats
one only dense search ranked first — which is exactly the right answer here,
where the best hits read on topic *and* contain the identifier asked about.

Two behaviours look like bugs:

- **Refusal.** Nothing clearing `min_rerank_score` returns zero passages, not
  the least-bad one. Handing the model whatever ranked highest is how a grounded
  system ends up citing a real document for a claim it does not make.
- **Superseded vintages are kept.** AML/KYC and Sanctions each exist as a 2023
  and a 2025 edition. The older one is marked and sorted last, never dropped:
  someone may be asking about it, and where the editions differ that difference
  is the answer. `hbl search` prints which families are doubled.

### Generation, and what is enforced rather than requested

`app/generate/` is the prompt plus the machinery around it. The failure it
exists to prevent is not a wrong answer — it is a *plausible* one. A model asked
about bank policy will produce fluent, correctly formatted, entirely invented
compliance guidance, and a reader cannot tell that from the real thing.

Two rules are code, not prompt text, because a prompt is a request:

- **A refusal never reaches the model.** With no passages there is nothing to
  ground an answer in, so `REFUSAL` is emitted directly. Asking a model to
  decline is asking it to do the one thing it is worst at.
- **Citations are checked against the passages that existed.** `[9]` when eight
  were supplied is an invented source, and the frontend would render a pill
  pointing at nothing. It is stripped from the stream and counted in
  `invented_citations`.

`_hold_partial_citation` exists because real streams break tokens anywhere,
including between `[1` and `2]`. A per-delta regex matches neither half, so a
valid citation goes unrecorded and an invented one survives. At most three
characters are ever held back, which costs nothing measurable — buffering whole
sentences would cost time-to-first-token, which this project treats as a
requirement.

The event order mirrors `StreamingState` in the frontend exactly:

    step(searching) → step(reading) → sources → step(composing) → delta* → done

**Sources before any text** is load-bearing, not tidiness: citation pills
resolve at render time, so a delta containing `[2]` that arrives before source 2
exists renders as a dead number.

`unused_sources` is the diagnostic in the other direction. Consistently high
means retrieval is handing over more than the answer needs, and prefill is the
largest cost in time-to-first-token — `HBL_RETRIEVAL_RERANK_TOP_K` is the knob.

### The API, and why one lock

`app/api/` — `hbl serve`. `POST /chat` (SSE), `GET /documents`,
`DELETE /documents/{id}`, `GET /health`.

`chat.py` is deliberately thin: `Answerer.stream` already emits events in the
order `StreamingState` expects, because that contract was settled while Phase 05
was written rather than retrofitted. All this does is format SSE frames.

One `Engine` holds the models, the registry and the vector store, and every
route that touches them goes through `engine.exclusive()`. That is not caution
about thread-safety alone — there is one GPU, or one set of CPU cores, and two
concurrent questions would run both half as fast at double the peak memory,
which is exactly how this machine segfaults. The queueing is explicit rather
than left to whichever allocation fails first. `Registry(same_thread=False)` is
only defensible because that lock exists.

The index fingerprint is checked at **startup**, so a mismatch is a server that
refuses to boot rather than one that answers nonsense confidently.

And nothing is invented to fill a response field. `mock.ts` carries a
`department` of "Global Compliance" — it reads like real metadata and was
written to make the mock look plausible. The documents have no such field, so
the API returns an empty string. `effectiveDate` is the document's year and
`version` its circular number; both are real. A system built to stop a model
inventing confident details should not open by inventing them itself.

## Next

**Wiring the frontend.** Replace the simulated stream in `frontend/src/App.tsx`
(`send`, `STEP_DELAYS`) with an SSE reader. The component tree does not change,
and `MetaRow` in `SourcePanel.tsx` should skip a value that is empty.

**Then upload.** `POST /documents` needs a job queue and a progress channel:
ingesting one PDF means routing every page, running a vision model over the
scans and re-embedding — up to an hour, which cannot be a request that holds a
connection open.

The full plan is `docs/build-plan.html`; open it in a browser.
