# Design Plan 05 — Assessment of `knowlytix/gmsh`, and the Revised Build

**Status:** revises plan 04 §3. Read after 04.
**Source:** `github.com/knowlytix/gmsh` @ clone, Apache-2.0, 413 Python modules.

---

## 1. Correction

In plan 02 §10 I wrote that the ingestion pipeline is ours to build, because the open `proofloop`
repo contains no ingestion code. That was accurate about `proofloop` and wrong about the wider
picture. **GEODE is in `gmsh`, it is Apache-2.0, and it implements most of what plan 04 scheduled as
WP9–WP11.** The build plan needs revising before any of it is written.

---

## 2. What GEODE actually provides

`knowlytix.knowledge.geode` describes itself as a self-supervised geometric extraction agent: a cheap
actor proposes triples (regex backbone plus a small local LLM), the GMS geometry judges them as a
*label-free critic*, a calibrated gate accepts/rejects/routes-to-review, and provenance points flags
back to the source span.

Public API, mapped to our work packages:

| GEODE | Our WP | Verdict |
|---|---|---|
| `ProvenanceLedger`, `Provenance`, `is_consistent` | WP2 (provenance) | **adopt** — including the consistency check plan 04 §2.3 proposed independently |
| `CompositionCritic`, `Flag` | LH5 (path-level conflict) | **adopt** — holonomy residual flags triples violating learned relation composition |
| `AnchorChecker`, `SumConstraint`, `enm_from_triples`, `numeric_facts_from_triples` | §6.2 conflicts, exact values | **adopt** — declared-constraint violation + exact numeric memory |
| `canonicalize_graph`, `Merge` | WP10 | **adopt** |
| `resolve_duplicates` | §6.1 dedup | **adopt** |
| `GeodeLoop`, `LoopResult` | WP11 reconciliation loop | **adopt** — ingest → train → diagnose → localize → repair → reconverge |
| `generate_entity_aliases`, `generate_relation_aliases` | lexicon | **adopt** |
| `ontology/` — `normalize_graph`, `OntologyMap`, `linkpred` | resolve/ | **adopt with care** — see §3 |
| `build_rag_store`, `build_calibrated_rag_store`, `store_from_triples` | store | adopt for the geometry tier |
| `agent_callable`, Qwen 3B/4B | llm/ | **evaluate** — a local actor is a real advantage (§5) |

`build_rag_store(md_path, config, *, llm, ingest_mode, max_iters, residual_threshold)` already offers
the hybrid mode asked for: `ingest_mode` is `"regex"` (deterministic seed, suited to tabular
documents), `"hybrid"` (regex plus LLM prose relations) or `"llm_only"`. `residual_threshold=None`
calibrates rather than taking a default — matching the book's calibration discipline.

The ontology layer is also better than I expected on one specific safety property: numeric tails are
never normalized, and a surface is only rewritten when normalization collapses two or more *observed*
surfaces — a singleton is never renamed, so a lone mis-normalized value cannot corrupt the graph.
That is a direct mitigation for the over-merge risk in plan 02 §D1, already implemented.

---

## 3. The decisive gap: emergent vocabulary vs declared vocabulary

GEODE's ontology layer builds *"a normalized, co-reference-resolved canonical vocabulary for the
extracted graph."* The vocabulary is **derived from what was extracted**, then cleaned. No
declared-schema constraint is exposed anywhere in the public API.

That is the opposite of the requirement:

| | GEODE | What we need |
|---|---|---|
| Direction | bottom-up — extract freely, normalize after | top-down — declare, then constrain extraction |
| Vocabulary | emergent from the corpus | canonical, closed per build |
| Enforcement | post-hoc merging | structured-output enum + signature validation at emission |
| Editing | not the model | a human-owned YAML file, versioned and diffed |

Both are legitimate. For an MRMG artifact that has to be predictable across builds and defensible to
a reviewer, the declared one is right, and it is what was specified: *it cannot run wild*.

**These compose rather than compete.** Constrain extraction to the declared schema, then run GEODE's
normalization over the *surface* forms within it. We get canonical relations by construction and
GEODE's surface/canonical separation — which preserves provenance back to the document's own spelling
— for entity names.

The one thing to verify before committing: whether `GeodeLoop` and `CompositionCritic` tolerate a
fixed relation set, or whether they assume they may rewrite relations during repair. If the latter,
we wrap the loop and reject relation rewrites at the boundary.

---

## 4. GEODE's own admitted limit, and why four work packages survive

The module docstring states the limitation plainly: the geometry provides label-free correction the
LLM alone cannot — errors that violate redundancy (relation composition) or declared constraints are
caught and fixed; **isolated values with no cross-check are not.** It calls this the honest limit.

This is the most useful sentence in the repository, because it tells us exactly where GEODE stops.

Our working policy document has both kinds. The attempt limit is stated three ways ("maximum of 3",
"up to 3 total", "must not make a fourth") — redundant, so GEODE's critic can cross-check it. A fee
amount, a single timeout, a lone canonical phrase has no second witness anywhere in the corpus, and
nothing in the geometry can tell a correct extraction from a plausible wrong one.

So these plan-04 packages stand, unchanged, as the cover for exactly that class:

- **Deterministic harvest (WP5)** — an isolated value extracted by rule rather than by model needs no
  cross-check, because it was never guessed.
- **Entailment check (WP9 / LH4)** — does the cited span actually support the claim. Independent of
  redundancy.
- **Two-witness rule for high-materiality triples (LH9)** — manufactures a second witness where the
  corpus provides none.
- **Provenance consistency metric (§2.3)** — a value-bearing triple whose span does not contain the
  value is caught deterministically, redundancy or not.

Without these, the pipeline is strongest exactly where the document repeats itself and weakest on the
single-mention facts that tend to be thresholds.

---

## 5. Other gaps, confirmed by reading

| Gap | Evidence | Who fills it |
|---|---|---|
| **No document readers** | no `pypdf`, `python-docx`, `pptx` or image handling anywhere in `knowlytix/`; `build_rag_store` takes `md_path`, a single markdown file | **us** — the old repo's `ingest/readers.py` already does this |
| **No diagram reading** | no image handling; the working policy's workflow is a flowchart | **us** — the old repo's three-pass vision read |
| **No multi-document corpus** | `ingest_document` is single-document; `_ingest_incremental` exists but is not a corpus manifest | **us** — WP4 manifest, hashes, version precedence |
| **No content-size batching** | not present in the API | **us** — WP7, plus the frozen-glossary two-pass |
| **Extraction-level determinism** | `seed` appears in the *trainer* (`embed_loop`); nothing addresses LLM decoding determinism | **us** — WP6 |
| **No fault injection for the pipeline** | none found | **us** — LH3 |
| **Human-decision durability** | `_ingest_incremental` is a starting point; content-keyed decisions are not | **us** — LH8, but read that function first |
| **Workflow-shaped relations** | `HAS_NEXT_STEP`, `OFFERS_DECISION`, `LEADS_TO` are our ontology's backbone, not GEODE's concern | **us** — WP1 |
| **GPU dependency** | `build_rag_store` imports torch, defaults to CUDA | operational decision (§6) |

---

## 6. Revised build plan

The shape changes from *build the pipeline* to **build the constrained front end and the corpus
layer, and hand a clean, schema-valid triple set to GEODE for correction.**

```
  documents (pdf/docx/xlsx/images/md)
        │  OURS — WP4 corpus, WP5 harvest, WP7 batching,
        │         WP8 extraction under the declared schema,
        │         WP9 admission (grounding + entailment + polarity)
        ▼
  schema-valid candidate triples + provenance
        │  GEODE — normalize → dedup → canonicalize →
        │          CompositionCritic + AnchorChecker → GeodeLoop repair
        ▼
  corrected graph
        │  OURS — WP11 integrity + path checks, decision log,
        │         WP13 reports, WP14 accuracy gate
        ▼
  defensible triple store
```

**Work package changes against plan 04:**

| WP | Change |
|---|---|
| WP2 provenance | **reduced** — adopt `ProvenanceLedger`; keep our derivation records where GEODE's ledger is span-only |
| WP10 canonicalisation | **reduced to integration** — `canonicalize_graph` + `normalize_graph` + `resolve_duplicates`, with relation rewrites rejected at the boundary (§3) |
| WP11 reconciliation | **reduced** — `GeodeLoop` is the loop; we keep integrity checks, the path/model-checking pass and the content-keyed decision log |
| WP5, WP6, WP7, WP8, WP9 | **unchanged** — this is the constrained front end GEODE does not have, and §4 is why it matters |
| WP1 schema | **unchanged, and now more load-bearing** — it is the whole difference between our design and GEODE's |
| WP3 harness + injectors | **unchanged** — GEODE brings no reproducibility or fault-injection story |
| WP4 corpus | **unchanged** — the single largest thing GEODE does not do |
| WP12 diagrams | **unchanged** |
| **WP16 (new)** | GEODE integration: adapter, fixed-relation-set verification (§3), version pinning, and a decision on the geometry tier |

Net effect: phase 1 gets **smaller and better**. The correction machinery we were going to write is
mature, tested and Apache-2.0; what remains is the part that is genuinely specific to what MRMG needs
— a declared vocabulary, real documents, and measurable trust.

---

## 7. New decisions this raises

1. **Do we take the geometry at all, or only the symbolic layer?** `CompositionCritic` and
   `AnchorChecker` need a trained GMS, which means torch and a GPU. Plan 04 deferred GMS to phase 6 on
   the basis that we would have to build it; that basis is gone. Recommendation: **take the symbolic
   parts now** (provenance, dedup, canonicalize, normalize) and **evaluate the geometric critic on the
   golden corpus** before committing to a GPU dependency in the build path — the fixture is small
   enough that the critic may earn its place or clearly not.
2. **Local Qwen actor.** GEODE defaults to a small local model (3B/4B) as the extraction actor. For a
   bank this is a genuine advantage — nothing leaves the box, and a self-hosted model gives real seed
   control, which is the determinism story WP6 needs. Worth evaluating against SafeChain rather than
   assuming SafeChain.
3. **Version pinning.** We now depend on a fast-moving external repo. Pin a commit, vendor if
   necessary, and treat a GEODE bump as a build-identity change (plan 02 §8).
4. **Upstreaming.** The corpus layer and declared-schema front end are things GEODE visibly lacks and
   the licence permits contributing back. Worth a decision, not urgent.

---

## 8. What to do first

Ahead of WP0, a **two-day spike**, because the answers change the plan again:

1. Run `build_rag_store` on `grounding/07` converted to markdown, `ingest_mode="hybrid"`. Record the
   triples, the critic flags and the provenance ledger.
2. Check whether a fixed relation set survives `GeodeLoop` repair (§3).
3. Run it twice and diff — establish GEODE's own reproducibility baseline before we build a harness
   around it.
4. Read `_ingest_incremental` against LH8.

That spike is worth more than another week of planning, and it de-risks the three decisions in §7.
