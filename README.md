# metric-new

Ontology-driven agent evaluation for **Metric 2.0** — MRMG independent testing of GenAI and agentic
use cases.

Policy documents go in. An evidence-grounded triple graph comes out, and from that graph two
directions:

- **forward** — the scenarios worth testing, and the contract each one must satisfy;
- **reverse** — given a real conversation and its telemetry, *where in the graph is each turn, and
  what did policy require there?*

The reverse direction is the point. A trace binds to the graph, every turn is placed in it, and the
graph then says which tools belonged there, which outcomes were legal, where it could go next and
which rules were in force — each traceable to the sentence of policy behind it.

The standard that sets: a fact this pipeline invents becomes a test an agent is failed for. So it
extracts what the source states, cites it, grades only what the telemetry can actually show, and
asks a person about the rest.

## Run it

```bash
pip install -e ".[dev]"

metric ui                 # browse the build, review it, grade traces — http://127.0.0.1:8765
metric evaluate           # the same thing on the command line
metric plan               # the variants each scenario would be run under
metric discover TRACE...  # draft a profile and an observed structure from telemetry
metric schema --schema schemas/core.ontology.yaml --extend schemas/card_auth.ontology.yaml
```

Two corpora ship with the repo. `corpus.yaml` is the card-authentication policy: a document, an
ontology, a telemetry profile, traces and a factor catalogue. `corpus-aop.yaml` is the opposite and
equally real case — production traces for an agent with no operating procedure, where the graph is
*observed* rather than declared and therefore cannot fail the agent it came from.

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
                             │                                            place each turn
                             │                                            trace/states.py
                             │                                                    │
                             └──────────────► EvaluationContract ◄────────────────┘
                          resolve_for_scenario | resolve_for_trace | resolve_turns
                                            contract/ · groundtruth.py
                                                       │
                                                       ▼
                                             verdicts, by dimension
                                                  evaluate/
```

**Placing a turn** is the hinge of the reverse direction, and it works without the agent's help. Read
`USES_TOOL` and `HAS_OUTCOME`/`OFFERS_DECISION` backwards and a tool says which states could have
called it, an outcome says which states could have produced it; intersect with what is reachable from
the previous turn and usually one survives. Measured on a trace stripped of every checkpoint: **5 of
6 turns recovered**, and the one that did nothing left unplaced rather than guessed.

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
| `trace/` | reading an OTEL export, binding it to the ontology, and placing each turn in the graph |
| `groundtruth.py` | what policy required at a turn, against what the turn did |
| `telemetry/` | the profile: what the ontology is called on the wire |
| `runtime/` | state, counters and order, replayed from a bound trace |
| `evaluate/` | one grader per assertion kind, and verdicts by dimension |
| `discover/` | traces in, a draft profile and observed structure out |
| `enrich/` | the factor catalogue and a pairwise design over it |
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
- **A rule learned by watching an agent cannot fail that agent.** Structure discovered from traces
  enters the graph as `telemetry`, and any assertion resting only on telemetry is forced to
  `advisory` — it would pass by construction, and a verdict that cannot fail is not a verdict.
- **Only a checkpoint can fail an agent.** A turn the agent placed itself is gradable. A turn we
  inferred is analysable and forced to advisory — inference is good enough to investigate with and
  not good enough to accuse with.
- **Enrichment cannot reach the contract.** A variant changes how the agent meets a situation, never
  what is required of it, so a failure under one level and a pass under another is attributable to
  the level. A factor that *does* change what is required is excluded from the design and named.

## Documents

| Path | What it is |
|---|---|
| `design/06-ingestion-v1.md` | the design being built |
| `design/07-build-notes.md` | where the ingestion code departs from that design, and why |
| `design/08-scenarios-contracts-evaluation.md` | scenarios, contracts, trace binding, evaluation and the UI. **Read this second.** |
| `design/09-discovery-enrichment-and-a-sweep.md` | discovery from traces, the enrichment layer, and what a performance and correctness sweep found |
| `design/10-reverse-mapping.md` | placing a turn in the graph, the inverse index, and ground truth per turn. **The reverse direction.** |
| `design/01`–`05` | the route there: ontology, failure modes, repo shape, loopholes, GEODE assessment |
| `grounding/README.md` | index and reading order for the grounding material |
| `grounding/06-key-findings-scenario-generator-vs-target.md` | gap analysis against the old Scenario Generator, with `file:line` evidence |
| `grounding/07-card-authentication-policy.md` | the working policy, and the golden fixture |
| `metric-source.zip` | snapshot of the Scenario Generator this replaces (`paras029/metric` @ `c4f6d8e`) |

## Status

Policy to verdict runs end to end in both directions, over two corpora: a policy with traces, and
traces with no policy. 187 tests; ruff and `mypy --strict` clean.

Not yet built: the independent annotation and accuracy gate, a simulator to turn a planned variant
into an actual run, a semantic oracle for paraphrase-permitted language, fault injection, and the
GEODE evaluation. `design/09` §4 lists the current limits and §5 the order to take them in.
