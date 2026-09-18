# Grounding documents

Reference material for the Metric Scenario Generator re-architecture. These are the inputs the
design work is built on — keep them here so later sessions and other readers start from the same
facts rather than re-deriving them.

| File | What it is | Use it for |
|---|---|---|
| `01-ontology-driven-agent-evaluation-strategy.md` | Consolidated strategy notes (Sept 2026): ontology-driven agent evaluation, `EvaluationContract`, dual-entry `GroundTruthResolver`, replaceable semantic oracle, phased roadmap. | The target architecture. The authoritative statement of *where we are going*. |
| `02-kg-grounded-testing-strategy-brief.md` | Handover brief contrasting *Beyond "Ship and Pray"* with the card-authentication procedural-KG POC, and proposing reverse (trace-first) ground-truth resolution. | The reverse-GT thesis, and the scenario-first vs trace-first distinction. |
| `03-otel-trace-sample-galileo.json` | Real Galileo turn-structured OTEL export from the production Decagon voicebot (AOP User Identification), PII-sanitized. | The ground reality of what a trace actually carries. Read before designing any `StateBinder`. |
| `04-eval-poc-codebase.md` | Curated `eval-poc` source: procedural Neo4j KG, `GroundTruthOracle`, `PathResolver`, `RuleCompiler`, `GroundTruthExtractor`, schemas, simulator, scenario artifacts. | The working prototype of the executable-oracle pattern: rules → typed assertions → occurrence-level ground truth. |
| `05-beyond-ship-and-pray-methodology-digest.md` | Working digest of the KnowlytiX methodology (concepts, taxonomies, API surface, design arguments). Not a reproduction of the book. | Base/enrichment separation, designed experiments, multi-level agentic evaluation, attribution, resilience, GMS as optional backend. |
| `06-key-findings-scenario-generator-vs-target.md` | Gap analysis of `paras029/metric` @ `c4f6d8e` against all of the above, with `file:line` evidence. | What we have, what is missing, what to keep, and what the re-architecture actually is. |

## Reading order

New to the project: `06` → `01` → `03` → `02` → `04` → `05`.

`06` is the entry point — it states the current position and the delta, and references the others
where detail is needed.

## Status notes

- The **book (`05`)** is a digest, not the source text. Go to the published work for wording.
- **`03` is the most under-used input.** It settles the question both strategy documents flag as
  decisive ("what metadata does the real agent emit?"), and the answer changes the reverse-GT plan —
  see `06` §3.
- Two discrepancies are unresolved and affect design: whether this repo or
  `scene_generator_latest.zip` is authoritative (capability-scoped enumeration), and the unsigned-off
  `VARIATIONS_BY_MATERIALITY` placeholder. See `06` §4.
