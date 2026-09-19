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
metric bases              # what this graph can be asked, and what was generated from it
metric evaluate           # grade the traces on the command line
metric plan               # the variants each base would be run under
metric run                # run the plan against an agent and grade every run
metric accuracy           # score the graph against a human reading of the same source
metric attribute RUNS     # which factor level made the agent fail, across a cohort
metric discover TRACE...  # draft a profile and an observed structure from telemetry
metric settings           # every tunable a build would use, and its digest
metric schema --schema schemas/core.ontology.yaml --extend schemas/card_auth.ontology.yaml
```

**[SETUP.md](SETUP.md)** has the whole install, including running it through SafeChain
inside the bank and standing up a new use case.

Two corpora ship with the repo. `corpus.yaml` is the card-authentication policy: a document, an
ontology, a telemetry profile, traces and a factor catalogue. `corpus-aop.yaml` is the opposite and
equally real case — production traces for an agent with no operating procedure, where the graph is
*observed* rather than declared and therefore cannot fail the agent it came from.

`corpus.yaml` says what to ingest, which ontology to read it with, which telemetry profile binds it
to a live agent, and which traces to grade. It points at a recorded extraction, so the whole thing
runs offline with no API key; remove `fixture:` to call the model.

The build writes to `--out`:

| File | What it holds |
|---|---|
| `graph.json` | admitted triples, canonically sorted, each with its spans and how it was found |
| `quarantine.json` | every rejected candidate, the criterion it failed, the quote it claimed |
| `scenarios.json` | the bases, the graph's capabilities, the taxonomy, and the settings used |
| `accuracy.json` | precision and recall against the annotation, and every disagreement |
| `plan.json` | the variants each base would be run under |
| `evaluations.json` | verdicts per trace, and ground truth per turn |
| `questions.yaml` | what the pipeline could not settle — edit it in place and re-run |
| `manifest.json` | build identity: corpus, schema, prompts, model, settings, code |
| `report.md` | what went wrong first, then the counts |

`metric.yaml` holds every tunable in the pipeline, shipped with the defaults written out,
and the whole file is hashed into build identity — two builds that used different settings
are different builds and say so. `provider: safechain` is the only edit needed to run this
inside American Express.

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
                  bases, by capability                                   a trace (OTEL)
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
| `scenario/` | what the graph can be asked, the base taxonomy, the generators, the answer check |
| `contract/` | assertions with severity, derivation level and provenance |
| `trace/` | reading an OTEL export, binding it to the ontology, and placing each turn in the graph |
| `groundtruth.py` | what policy required at a turn, against what the turn did |
| `telemetry/` | the profile: what the ontology is called on the wire |
| `runtime/` | state, counters and order, replayed from a bound trace |
| `evaluate/` | one grader per assertion kind, and verdicts by dimension |
| `discover/` | traces in, a draft profile and observed structure out |
| `enrich/` | the factor catalogue, relevance and profiles, the design over it, the render seam |
| `run/` | driving a planned variant against an agent, and the trace that comes back |
| `attribution.py` | which factor level made the agent fail, and which component |
| `regression.py` | the same question with the other factors held fixed |
| `accuracy.py` | is the graph right? precision and recall against a human reading |
| `refine/` | names that read as names, and rules that assert nothing |
| `settings.py` | every tunable, hashed into build identity |
| `ui/` | the pages, stdlib server, SVG workflow layout. Three type voices: sans is the tool speaking, **serif is only ever the source document's own words**, mono is the record. No font is fetched — an internal network usually cannot reach a font host |

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
- **A category is admissible only if the graph exposes the capability it needs.** Test material is
  derived from the graph outward, not from a list of prompts. A policy that states no prohibitions
  generates no prohibition material and says why — rather than reporting a category at zero, which
  is indistinguishable from a bug.
- **A generated base is not admitted until its answer is recovered a second way.** The generators
  read indexes; the check scans the flat triple list. Its first run found a real disagreement — in
  the checker, which was reading a different population. A generator walking a wrongly-filled index
  produces confident, well-formed, incorrect tests, and nothing downstream can tell.
- **A factor is crossed only where it means something.** Numeric framing says nothing about a route
  through the graph. Crossing it in spends the budget on cells that cannot fail for the reason the
  column claims to measure, and dilutes every attribution drawn from it.
- **Selecting a factor is data; rendering its levels is code.** The design records `clarity=garbled`;
  making a prompt read garbled is an installation's own work. The default renderer varies nothing
  and says so, because nothing should be attributed to a column that never reached the agent.
- **No rate without an interval, no comparison without correction.** Four of five passing is not 80%
  — the interval runs from 38% to 96%. Dozens of tests at a nominal 5% produce a finding by chance,
  so the whole family is corrected before anything is called an effect.
- **A marginal comparison cannot tell an effect from the company it keeps.** A pairwise design does
  not balance every factor within every other's levels, so a level inherits the failures of the one
  it was paired with. Measured: an agent built to fail under exactly one level produced *five*
  marginal findings and one adjusted one. Both are reported, and the difference is named.
- **A name is not a sentence.** Policy states rules as sentences, so the extractor named one rule
  three ways and the graph carried three nodes, three assertions and three questions for one fact.
  Labels the source gives are taken deterministically; the rest needs a model, and where none is
  available the names are reported rather than mangled.
- **A rule that asserts nothing is a recall defect, not a question.** Nine rules carried only their
  own text and a severity — nothing governed by them, nothing required, forbidden or bounded. They
  could never have been checked against anything. They leave the graph, and *one* question names all
  of them, because nine identical questions is not nine decisions.
- **What is policy is a fact about the corpus, not a judgement for a model.** This repository's own
  notes about why the working policy is a good first corpus are written in the same imperative voice
  as the policy, and the extractor read eight Rules out of them. `skip_sections:` in the corpus file
  is where that belongs.
- **Everything rests on the graph being right, so the graph is measured.** Every other check in
  here confirms the graph is internally *consistent*, which a confidently wrong graph also is. A
  person reads the corpus, writes down the triples in it, and precision and recall are reported
  against that. Precision is gated harder than recall, because an invented fact fails an agent
  unjustly while a missing one is only a gap — and high-materiality relations harder still.
- **A self-marked annotation never clears a build.** Written by whoever wrote the prompts, it
  measures agreement with the pipeline's own assumptions. Code cannot verify independence, so the
  gold file declares it and the declaration is printed beside every number it produced.
- **The runner does not know the answer.** It drives a conversation and records a `Trace` — the same
  type a production export produces — and grading happens afterwards, through the same evaluator.
  A harness that both stages a situation and judges it is marking its own homework.
- **A run that could not have failed does not reach attribution.** No turn the agent placed itself,
  or the situation never arose: either way it tells you nothing, and a cohort padded with them shows
  every factor level doing well.

## Documents

| Path | What it is |
|---|---|
| `design/06-ingestion-v1.md` | the design being built |
| `design/07-build-notes.md` | where the ingestion code departs from that design, and why |
| `design/08-scenarios-contracts-evaluation.md` | scenarios, contracts, trace binding, evaluation and the UI. **Read this second.** |
| `design/09-discovery-enrichment-and-a-sweep.md` | discovery from traces, the enrichment layer, and what a performance and correctness sweep found |
| `design/10-reverse-mapping.md` | placing a turn in the graph, the inverse index, and ground truth per turn. **The reverse direction.** |
| `design/11-bases-enrichment-and-deployment.md` | the base taxonomy, the answer check, the enrichment design space, settings, and SafeChain |
| `design/12-running-and-attribution.md` | driving a plan against an agent, the four bugs a clean baseline caught, and adjusted attribution |
| `design/13-accuracy.md` | the accuracy gate, the first measurement, and what it found |
| `design/14-refinement.md` | why 49 questions became 35, and what a name is |
| `annotations/card_auth.gold.yaml` | a human reading of the working policy — **read its header first** |
| `SETUP.md` | installing it, running it through SafeChain, and standing up a new use case |
| `design/01`–`05` | the route there: ontology, failure modes, repo shape, loopholes, GEODE assessment |
| `grounding/README.md` | index and reading order for the grounding material |
| `grounding/06-key-findings-scenario-generator-vs-target.md` | gap analysis against the old Scenario Generator, with `file:line` evidence |
| `grounding/07-card-authentication-policy.md` | the working policy, and the golden fixture |
| `metric-source.zip` | snapshot of the Scenario Generator this replaces (`paras029/metric` @ `c4f6d8e`) |

## Status

Policy to verdict runs end to end in both directions, over two corpora: a policy with traces, and
traces with no policy. **Plan to attribution now closes too**: `metric run` drives every planned
variant against an agent and `metric attribute` says which factor level caused the failures.
330 tests; ruff and `mypy --strict` clean.

Measured on the card-authentication policy: 6 journey paths become **32 bases across 5 families**,
each checked by recovering its answer from the triples a second time; 410 planned runs; and an agent
built to degrade under exactly one factor level is recovered as that level and no other
(odds ratio 0.012, q < 0.0001, pseudo-R² 0.87).

**The accuracy gate now exists and the build does not clear it.** Scored against a human reading of
the card-authentication policy: strict precision 70%, recall 70%; relaxed 75% / 79%; high-materiality
precision 67% against a 98% bar. The defects are listed, not just counted — 7 invented, 7 missed, 2
read correctly under a different name. That is the real state of the extraction and every other
number in this repository sits on top of it.

The annotation was written by the author of the extraction prompts and says so, so it reports
`trustworthy: false` and cannot clear a build. **Commissioning an independent one is the single
highest-value thing left**, and it is now a data task rather than a code one.

Also not yet built: φp space-filling designs, interaction terms in the attribution model, a semantic
oracle for paraphrase-permitted language, and the GEODE evaluation. `design/13` §5 lists the current
limits.
