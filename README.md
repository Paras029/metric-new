# metric-new

Ontology-driven ingestion for **Metric 2.0** — MRMG independent testing of GenAI and agentic use
cases.

Policy documents go in; an evidence-grounded triple graph comes out, together with everything that
was rejected and everything still open. The graph is the ground truth a live agent is later tested
against, which sets the standard: a fact this pipeline invents becomes a test an agent is failed
for. So it extracts what the source states, cites it, and asks a person about the rest.

## Run it

```bash
pip install -e ".[dev]"

metric schema --schema schemas/core.ontology.yaml --extend schemas/card_auth.ontology.yaml
metric ingest grounding/07-card-authentication-policy.md \
  --schema schemas/core.ontology.yaml --extend schemas/card_auth.ontology.yaml \
  --out build
```

The build writes five files to `--out`:

| File | What it holds |
|---|---|
| `graph.json` | admitted triples, canonically sorted, each with its spans and how it was found |
| `quarantine.json` | every rejected candidate, the criterion it failed, the quote it claimed |
| `questions.yaml` | what the pipeline could not settle — edit it in place and re-run |
| `manifest.json` | build identity: corpus, schema, prompts, model, code |
| `report.md` | what went wrong first, then the counts |

`--replay` serves every model call from the cache and errors on a miss, so a rebuild cannot quietly
become a new build. Model calls need `ANTHROPIC_API_KEY` or `ant auth login`.

## How it works

```
documents ─► passages ─► candidates ─► batches + frozen glossary ─► candidates ─► triples ─► graph
  corpus/    corpus/     extract/       extract/                     extract/     admit/    reconcile/
                         harvest.py     batching.py, glossary.py     triples.py   gate.py   run.py
                         deterministic  pass A                       pass B (LLM)
```

Seven stages. Six are deterministic. Pass B is the only place a model decides anything, and
everything it produces has to survive the gate.

| Package | Responsibility |
|---|---|
| `ontology/` | types, content-hash identity, canonical forms, the schema loader |
| `corpus/` | readers (md, txt, pdf, docx, xlsx, image), furniture stripping, passages, the manifest |
| `extract/` | deterministic harvest, content-size batching, the frozen glossary, model extraction |
| `llm/` | the single model call, the response cache, prompts built from the active ontology |
| `admit/` | quote location and the ordered admission criteria |
| `reconcile/` | merge, the witness bar, typed conflicts, conditional integrity |
| `graph/`, `reports.py`, `review.py`, `cli.py` | the graph, the outputs, the review loop |

The load-bearing ideas, each with the failure it prevents:

- **The schema is closed per build and human-owned between builds.** `schemas/*.yaml` drives the
  response enum, so a model cannot invent a relation — it is unsayable, not merely rejected. The
  file is versioned and diffable, so the vocabulary is not frozen forever.
- **Identity is a content hash, never a counter.** Two builds over the same corpus agree.
- **Batching is by content size, not by relation type.** Each batch is asked for everything it
  contains, once, with one passage of context either side.
- **The glossary is harvested in a separate pass and frozen.** Otherwise batch *N* depends on
  batches 1…*N*−1, and reordering the corpus would change the graph.
- **A candidate is not a triple until it passes.** Schema, then quote located, then polarity, then
  value present. The span records the *source's* characters, never the model's.
- **Restatements merge and keep every citation.** One limit stated three ways is one triple with
  three spans.
- **Nothing is inferred to make the graph look complete.** An outcome the corpus never routes gets
  a question, not an invented destination.

## Documents

| Path | What it is |
|---|---|
| `design/06-ingestion-v1.md` | the design being built |
| `design/07-build-notes.md` | where the code departs from that design, and why. **Read this second.** |
| `design/01`–`05` | the route there: ontology, failure modes, repo shape, loopholes, GEODE assessment |
| `grounding/README.md` | index and reading order for the grounding material |
| `grounding/06-key-findings-scenario-generator-vs-target.md` | gap analysis against the old Scenario Generator, with `file:line` evidence |
| `grounding/07-card-authentication-policy.md` | the working policy, and the golden fixture |
| `metric-source.zip` | snapshot of the Scenario Generator this replaces (`paras029/metric` @ `c4f6d8e`) |

## Status

The ingestion pipeline runs end to end and is tested against the golden fixture. Not yet built: the
reproducibility harness, the independent annotation and accuracy gate, the fault injectors, the
GEODE evaluation, and the UI. `design/07` §6 lists these in the order they matter, and §7 the
decisions still open.
