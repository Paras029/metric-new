# metric-new

Ontology-driven agent evaluation for **Metric 2.0** — MRMG independent testing of GenAI and agentic
use cases.

Policy documents go in. An evidence-grounded triple graph comes out, and from that graph: the
scenarios worth testing, what policy required at any point of a real conversation, and a verdict on
whether the agent did it — each one traceable to the sentence of policy behind it.

The standard that sets: a fact this pipeline invents becomes a test an agent is failed for. So it
extracts what the source states, cites it, grades only what the telemetry can actually show, and
asks a person about the rest.

## Run it

```bash
pip install -e ".[dev]"

metric ui                 # browse the build, review it, grade traces — http://127.0.0.1:8765
metric evaluate           # the same thing on the command line
metric schema --schema schemas/core.ontology.yaml --extend schemas/card_auth.ontology.yaml
```

`corpus.yaml` says what to ingest, which ontology to read it with, which telemetry profile binds it
to a live agent, and which traces to grade. It points at a recorded extraction, so the whole thing
runs offline with no API key; remove `fixture:` to call the model.

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
                          documents ──► passages ──► candidates ──► triples ──► GRAPH
                           corpus/       corpus/     harvest +      admit/     reconcile/
                                                     extract/       gate
                                                                                  │
                             ┌────────────────────────────────────────────────────┤
                             ▼                                                    ▼
                    scenarios (paths)                                    a trace (OTEL)
                      scenario/                                            trace/ + profile
                             │                                                    │
                             └──────────────► EvaluationContract ◄────────────────┘
                                   resolve_for_scenario | resolve_for_trace
                                                  contract/
                                                       │
                                                       ▼
                                             verdicts, by dimension
                                                  evaluate/
```

One compiler, two entry points. A generated scenario and an observed trace resolve the *same*
assertions from the *same* graph and differ only in what they narrow to — which is what stops a
synthetic benchmark drifting away from production evaluation.

| Package | Responsibility |
|---|---|
| `ontology/` | types, content-hash identity, canonical forms, the schema loader |
| `corpus/` | readers (md, txt, pdf, docx, xlsx, image), furniture stripping, passages, the manifest |
| `extract/` | deterministic harvest, content-size batching, the frozen glossary, model extraction |
| `llm/` | the single model call, the response cache, prompts built from the active ontology |
| `admit/` | quote location and the ordered admission criteria |
| `reconcile/` | merge, the witness bar, typed conflicts, conditional integrity |
| `scenario/` | bounded path enumeration, plus a focused path back to every branch it missed |
| `contract/` | assertions with severity, derivation level and provenance |
| `trace/` | reading an OTEL export, and binding what it shows to the ontology |
| `telemetry/` | the profile: what the ontology is called on the wire |
| `runtime/` | state, counters and order, replayed from a bound trace |
| `evaluate/` | one grader per assertion kind, and verdicts by dimension |
| `ui/` | the pages, stdlib server, SVG workflow layout |

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
- **A relation declares its own check, in the ontology.** `checks: {kind: action_forbidden, …}` sits
  beside `domain` and `range`, so a new use case declares how its relations are graded in the same
  edit that introduces them. A relation that declares neither a check nor `not_checkable: true` is
  reported rather than silently graded by nothing.
- **Binding is declared, then lexical, then reported.** A telemetry profile says what the ontology is
  called on the wire. Nothing is guessed: evaluating a trace from a different agent gives 0% binding
  coverage and no verdicts at all, rather than confident nonsense.
- **Four verdicts, not two.** `not_applicable` (the situation never arose) and `undecided` (the
  telemetry cannot show it) are kept apart from pass and fail, because folding either into a pass is
  how an evaluator comes to look confident about a blind spot.
- **Nothing blocks until a person approves it.** An expectation resting on a single unreviewed model
  reading is `advisory` and cannot fail an agent. Approving it in the review queue is what makes it
  able to.

## Documents

| Path | What it is |
|---|---|
| `design/06-ingestion-v1.md` | the design being built |
| `design/07-build-notes.md` | where the ingestion code departs from that design, and why |
| `design/08-scenarios-contracts-evaluation.md` | scenarios, contracts, trace binding, evaluation and the UI. **Read this second.** |
| `design/01`–`05` | the route there: ontology, failure modes, repo shape, loopholes, GEODE assessment |
| `grounding/README.md` | index and reading order for the grounding material |
| `grounding/06-key-findings-scenario-generator-vs-target.md` | gap analysis against the old Scenario Generator, with `file:line` evidence |
| `grounding/07-card-authentication-policy.md` | the working policy, and the golden fixture |
| `metric-source.zip` | snapshot of the Scenario Generator this replaces (`paras029/metric` @ `c4f6d8e`) |

## Status

Policy to verdict runs end to end and is tested against the working policy, a synthetic run of that
policy, and a real production trace from a different agent. 138 tests; ruff and `mypy --strict`
clean.

Not yet built: an ontology and profile for the agent we have real traces of, the independent
annotation and accuracy gate, enrichment and DOE, a semantic oracle for paraphrase-permitted
language, fault injection, and the GEODE evaluation. `design/08` §7 lists the known limits and §8 the
order to take them in.
