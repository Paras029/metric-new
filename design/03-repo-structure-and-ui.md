# Design Plan 03 — Repository Structure and the UI

**Status:** proposal for review. No code written yet.

---

## 1. Repository layout

`src/` layout, so the installed package is what tests import and a stale working directory cannot
shadow it.

```
metric-new/
├── pyproject.toml              single source of deps, tooling, entry points
├── README.md
├── schemas/                    DATA, human-owned, versioned, diffable
│   ├── core.ontology.yaml          structural types + core relations with signatures
│   └── card_auth.ontology.yaml     use-case extension: domain types, added relations
├── prompts/                    DATA, hashed into build identity
│   ├── glossary.harvest.md
│   ├── triples.extract.md
│   ├── diagram.read.md · diagram.synthesise.md · diagram.repair.md
│   └── entailment.check.md
├── src/metric/
│   ├── ontology/               schema loading, validation, triple model, IDs
│   │   ├── schema.py               load core+extension, resolve, freeze
│   │   ├── types.py                Triple, Entity, EvidenceSpan, Provenance
│   │   ├── ids.py                  deterministic entity/passage id derivation
│   │   └── validate.py             signature, cardinality, polarity checks
│   ├── corpus/                 documents in, passages out
│   │   ├── manifest.py             file hashes, versions, precedence declarations
│   │   ├── readers/                pdf, docx, pptx, xlsx, md, csv, image
│   │   ├── furniture.py            repeated header/footer stripping
│   │   ├── passages.py             structure-aware passaging, stable ids
│   │   └── redaction.py
│   ├── extract/                candidates out
│   │   ├── batching.py             token-budgeted, structure-aware, overlapping
│   │   ├── deterministic.py        regex/table/modal harvest
│   │   ├── glossary.py             pass A
│   │   ├── triples.py              pass B
│   │   ├── diagrams.py             three-pass vision reading
│   │   └── validators/             signature, polarity, modality, entailment
│   ├── admit/                  the gate
│   │   ├── grounding.py            quote location (ported from the old repo)
│   │   ├── entailment.py           does the span support the claim
│   │   ├── gate.py                 admission criteria, in order
│   │   └── quarantine.py           rejected candidates + reason
│   ├── resolve/                canonicalisation
│   │   ├── canonical.py            constraint/deontic canonical forms
│   │   ├── entities.py             the resolution cascade
│   │   ├── lexicon.py              alias proposals and approvals
│   │   └── merges.py               merge log, reversibility
│   ├── reconcile/              the loop
│   │   ├── dedup.py · conflicts.py · integrity.py
│   │   ├── decisions.py            the decision log
│   │   └── loop.py                 ordering, monotonicity, termination
│   ├── store/                  persistence
│   │   ├── triples.py              canonical sorted file-backed store
│   │   ├── evidence.py · build.py  manifest, identity, atomic promotion
│   │   └── graph.py                load into an in-memory graph for querying
│   ├── semantic/               the deferred seam
│   │   ├── oracle.py               SemanticOracle protocol
│   │   └── baseline.py             embeddings + reranker/NLI + calibration
│   ├── llm/                    provider-agnostic calling
│   │   ├── gateway.py              SafeChain/LangChain, tiers, retries
│   │   ├── structured.py           schema-constrained output, repair
│   │   ├── determinism.py          seeds, sorting, prompt assembly, n-vote
│   │   └── prompts.py              loader + library hash
│   ├── reports/                coverage, reproducibility, drift, questions
│   ├── webapp/                 §2
│   └── cli.py
├── tests/                      mirrors src/metric, plus:
│   ├── fixtures/card_auth/         the golden corpus and its hand-written graph
│   ├── test_reproducibility.py     the harness gate
│   └── test_golden_graph.py        expected triples for grounding/07
└── workspaces/                 gitignored run output
```

**Why these boundaries.** Each directory is one stage of the pipeline with one output type, so a
stage can be tested against fixed inputs without the rest existing. `admit/` is separate from
`extract/` deliberately: extraction proposes, admission decides, and keeping them apart is what makes
"what was thrown away and why" answerable. `semantic/` is one directory because it is the thing we
intend to replace.

**Practices, enforced not just stated.** `ruff` + `mypy --strict` in CI; `pytest` with the
reproducibility harness as a gate; no module over ~300 lines without a reason; dataclasses/pydantic at
boundaries; no bare `except`; every LLM call goes through `llm/` so determinism controls cannot be
bypassed. Comments explain *why*, never *what* — the old repo is genuinely good at this and it is the
one stylistic thing worth carrying over wholesale.

---

## 2. The UI

The old interface had the right shape — a workspace per use case, stages down the left, run/stop,
downloadable artifacts — and poor execution. Keep the shape. The upgrades that matter are not
cosmetic: **the new pipeline produces review queues the old one had no concept of**, and the UI is
where those get worked.

### 2.1 What is genuinely new

| Screen | Why it exists |
|---|---|
| **Quarantine** | every rejected candidate with its failing criterion and evidence. The fastest way to see a broken extractor. |
| **Conflicts** | typed conflict pairs side by side with both evidence spans; resolve, defer, or mark as version precedence. |
| **Merge proposals** | alias/entity merges awaiting approval. Approved aliases become authoritative for later builds (plan 02 §D4), so this screen has real consequences. |
| **Open questions** | answered inline; answers become human-attributed evidence. |
| **Build history** | identity tuple per build, and the reproducibility diff between any two. |
| **Schema** | view the active core + extension, and what a use case added. Editing is a file change and a review, not an in-app action. |

### 2.2 The three graph views

- **Workflow view — primary.** `HAS_NEXT_STEP` / `OFFERS_DECISION` / `LEADS_TO` only, top to bottom,
  retry loops through a side lane as dashed edges. The old `graphview.py` lane routing is the reason
  the current picture is readable; port that logic. Each node badges its attached rules by severity,
  thresholds and declared variables; click to expand statement + evidence + source.
- **Triple view.** Filterable table, inline edit validated against the active schema, every row
  showing method / confidence / evidence / status. Human edits recorded as `extraction_method=human`.
- **Knowledge-graph view.** 2D, layered by entity type, hard filtering by relation family and entity
  type. 3D stays a presentation mode, not the working view — the reasoning is in plan 01 §5.3.

### 2.3 Stack

The constraint that shaped the old UI — internal package mirrors, Flask 1.x-compatible interfaces —
probably still applies, so a heavy SPA toolchain is the wrong bet.

**Recommendation:** Flask for the shell and routing; **HTMX** for interactivity (one vendored file, no
build step, no npm); **Cytoscape.js** for both graph views (vendored, mature, good layout control
including the lane routing the workflow view needs); server-rendered tables with client-side filter.
Design tokens in one stylesheet, dark/light from the start.

This is a real upgrade — live progress, review queues, proper graph interaction — with no build
pipeline an internal mirror has to serve. **Open question:** is the Flask 1.x constraint still live?
If not, the options widen, but I would still avoid an SPA for this.

When we build it, the `frontend-design` skill applies — the old UI's problem was that it looked like
un-designed defaults, and that is exactly what that guidance is for.

---

## 3. Open questions from this plan

1. **Flask 1.x / internal mirror constraint** — still binding?
2. **Store choice** — file-backed triples as source of truth (diffable, `git diff` *is* the
   reproducibility diff) with a graph store for querying, vs Neo4j as truth. Plan 01 §11.3 recommends
   the former; worth confirming before `store/` is written.
3. **Model access** — is SafeChain still the approved gateway, and does it expose a seed parameter?
   Determinism work depends on the answer.
