# Backend

The offline half of the assistant. Phases 00 and 01 are done: configuration,
structured logging, a headless CLI, the four provider contracts, per-page
routing, the OCR bench-off, and extraction to markdown. No chunking, index,
retrieval or API yet — those are Phases 02–06.

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
and the EU sanctions map, and that is content.

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

## Next

**Index, registry and true deletion** (Phase 03) — Qdrant with payload indexes,
a SQLite registry with FTS5 for keyword search in the same database, so
deleting a document removes its vectors, keyword entries and registry row in
one transaction.

The full plan is `docs/build-plan.html`; open it in a browser.
