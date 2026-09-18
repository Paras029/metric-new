# metric-grounding

Reference material for the **Metric 2.0** agent-evaluation re-architecture — MRMG independent
testing of GenAI and agentic use cases.

This repository holds the inputs the design work is built on, so later work starts from the same
facts rather than re-deriving them. It is documentation and an archive; it is not the running code.

## Contents

| Path | What it is |
|---|---|
| `grounding/README.md` | Index and reading order for the grounding documents. **Start here.** |
| `grounding/01-ontology-driven-agent-evaluation-strategy.md` | Target architecture: ontology-driven evaluation, `EvaluationContract`, dual-entry `GroundTruthResolver`, replaceable semantic oracle, phased roadmap. |
| `grounding/02-kg-grounded-testing-strategy-brief.md` | Handover brief: procedural-KG POC vs the KnowlytiX methodology, and the reverse (trace-first) ground-truth thesis. |
| `grounding/03-otel-trace-sample-galileo.json` | Real Galileo turn-structured OTEL export from the production Decagon voicebot (AOP User Identification), PII-sanitized. |
| `grounding/04-eval-poc-codebase.md` | Curated `eval-poc` source — the working prototype of the executable-oracle pattern. |
| `grounding/05-beyond-ship-and-pray-methodology-digest.md` | Working digest of the KnowlytiX methodology (concepts, taxonomies, API surface). Not a reproduction of the book. |
| `grounding/06-key-findings-scenario-generator-vs-target.md` | Gap analysis of the Scenario Generator against all of the above, with `file:line` evidence. |
| `metric-source.zip` | Snapshot of the Scenario Generator source (`paras029/metric` @ `c4f6d8e`, `.git` excluded) that the gap analysis was written against. |

## Where to start

`grounding/06-key-findings-scenario-generator-vs-target.md` — it states the current position, the
delta to the target, and points into the other documents where detail is needed.

## Status

- The book digest (`05`) is a summary for engineering use, not the source text.
- `03` is the most decisive and least-read input: it settles what production traces actually carry,
  which changes the trace-first design. See `06` §3.
- Two discrepancies remain open and affect design — see `06` §4.
