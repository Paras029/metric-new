# Design Plan 04 — Loopholes, Provenance, and the Exact Build Plan

**Status:** the plan to execute. §1 is a review of our own approach against the book and the
reference code; §2 is the provenance design; §3 is the work breakdown.

---

## 1. Loopholes in our approach, and the fixes

Found by re-reading plans 01–03 against *Beyond "Ship and Pray"*, the `proofloop` source, eval-poc
and the working policy document.

| # | Loophole | Severity | Fix |
|---|---|---|---|
| LH1 | The golden fixture is circular | high | dual independent derivation; annotation by someone who did not write the prompts |
| LH2 | Reproducibility is not accuracy | **critical** | adopt the book's self-answering precondition; add precision/recall against annotation |
| LH3 | Nothing proves the detectors fire | **critical** | fault injection into our own pipeline; detection rate as a CI metric |
| LH4 | The entailment check is an unvalidated LLM, correlated with the extractor | high | different model, calibrated on a labelled cohort, disagreement → quarantine |
| LH5 | Conflict detection is pairwise; path-level inconsistency is invisible | high | model-checking pass over enumerated paths |
| LH6 | No distinction between extraction defects and source defects | medium | two finding classes; source defects are a deliverable back to the policy owner |
| LH7 | Telemetry mappings have no source in the policy | high | proposed with evidence, human-approved, never auto-admitted |
| LH8 | Re-ingestion destroys human decisions | **critical** | decisions keyed to content hashes; survive unchanged text, invalidate on change |
| LH9 | All triples are treated as equally important | medium | materiality tiering at ingestion drives admission strictness |
| LH10 | Required-vs-generated language never reaches evaluation | low | thread `GENERATION_ALLOWED` into the grading mode |
| LH11 | `proofloop`'s judge cannot run without the licensed backend | medium | build ours behind the same interface; do not plan on reusing theirs |

### LH2 — Reproducibility is not accuracy *(critical)*

Plan 02 §8 gates on a reproducibility harness: run ingestion twice, diff the triples, require
Jaccard 1.0. **Two runs can agree perfectly on the same wrong graph.** We built a stability measure
and called it quality. Worse, determinism makes an error *stable*, which reads as correctness — the
same trap as LH8's alias poisoning.

The book states the missing gate directly in its ground-truth builder: before any score built on the
store is trusted, *the graph must answer its own generated questions perfectly — a baseline of 1.0.*

**Fix — two gates, not one:**

- **Stability gate** (have): same inputs → same graph.
- **Accuracy gate** (new): two parts.
  1. **Self-answering precondition.** Generate questions mechanically from the admitted graph
     ("what is the attempt limit for `authenticate_customer`?", "where does outcome `FAILED` lead when
     `attempt_count < 3`?"), answer each *from the source passages* rather than from the graph, and
     require a perfect baseline. A question the documents cannot answer means the graph asserts
     something the source does not.
  2. **Precision/recall against annotation.** A human-annotated triple set for the golden corpus.
     Precision = admitted triples that are correct; recall = annotated triples we found. Reported per
     relation family, because recall on `HAS_NEXT_STEP` and on `RULE_FORBIDS` fail for different
     reasons.

Neither gate is optional, and shipping the stability gate alone would be actively misleading.

### LH3 — Nothing proves the detectors fire *(critical)*

Plan 02 §4 catalogues ~30 failure modes and assigns each a detector. Not one line of that is tested.
A detector that silently never fires is indistinguishable from a clean corpus.

**Fix — fault injection one layer up.** `proofloop/evaluation/failure_modes.py` uses the right
pattern for agents: an enum of modes, one injector per mode, each mutating a scenario. We apply it to
our own pipeline: one injector per catalogued failure, mutating the *corpus or the intermediate
state*, asserting the corresponding detector fires.

```
inject_polarity_flip        → flips a modal in a passage      → §C4 validator must catch
inject_split_rule           → forces a batch boundary mid-rule → §B1 detector must catch
inject_restated_fact        → same constraint, third phrasing  → dedup must collapse to one
inject_contradictory_value  → second fee value in a new doc    → §E conflict must fire
inject_detached_table_header→ strips a table header            → §A2 detector must catch
inject_fabricated_quote     → alters a quote post-extraction   → grounding must discard
inject_orphan_outcome       → removes a LEADS_TO               → §6.3 integrity must raise
```

**Detection rate per failure mode becomes a CI metric**, exactly as the book measures fail-loud
detection under tool faults. A mode with no injector is a mode we are pretending to handle.

### LH1 — The golden fixture is circular

We plan to hand-write the correct graph for `grounding/07` and assert against it — but we write both
the extractor and the answer key. A misreading of the policy passes green.

**Fix, two parts.** (a) **Dual independent derivation**: the workflow backbone is derivable from the
prose (§3) *and* from the flowchart (§8). Where both exist, agreement is corroboration and
disagreement is a review item — never an auto-merge. This is the book's functionality-check logic
(symbolic and geometric recovery must agree; disagreement is a signal about the oracle, not a tie to
break) applied to ingestion. (b) The annotation is written by someone who did not write the
extraction prompts.

### LH5 — Path-level inconsistency is invisible

Our conflict detection compares triples pairwise over canonical keys. Whole classes of inconsistency
only appear when you *walk* the graph: a rule that no path can satisfy, a rule unreachable on every
path, a terminal state no path reaches, a prohibition that the only legal route violates.

**Fix — a model-checking pass.** Enumerate paths (the old repo's enumeration logic), evaluate every
rule's condition along each. Report: rules violated on every path (rule or graph is wrong), rules
never exercised by any path (dead rule, or missing branch), unreachable terminal states. eval-poc
already evaluates rules against a *resolved* path; this generalises it to all paths and runs it as an
ingestion check rather than a scenario-time one.

### LH8 — Re-ingestion destroys human decisions *(critical)*

Every approved alias, resolved conflict and answered open question is human effort. A re-run after a
policy edit currently throws all of it away. That makes the tool single-use, which is the quiet way
this whole thing fails in practice.

**Fix — decisions are content-keyed.** A decision is keyed by the hash of the *text it was made
about*, not by a triple id or a run id. On re-ingestion: unchanged text → the decision is re-applied
automatically; changed text → the decision is invalidated and re-queued, with the diff shown. The
decision log is a durable artifact of the workspace, versioned alongside the schema, and never
regenerated.

### LH7 — Telemetry mappings have no source in the policy

`EMITTED_AS_TOOL`, `EMITTED_AS_CHECKPOINT` and friends cannot be extracted from a policy document —
no policy mentions `check_fullssn_or_cm15`. They come from the telemetry profile, and if a model
guesses them, a wrong binding produces wrong ground truth silently and permanently.

**Fix.** Telemetry mappings are **proposals with evidence** (name similarity, position in trace,
co-occurrence with a bound tool), presented for human approval, never auto-admitted. Unmapped symbols
on either side are reported as drift, not resolved.

### LH9 — Materiality tiering makes robustness affordable

A wrong canonical greeting is trivial; a wrong retry limit is critical. Treating every triple with the
same rigour is either too expensive or too weak. Tier at ingestion — deontic triples, thresholds and
terminal transitions are high; descriptive text is low — and let the tier drive admission strictness:
high-materiality triples need two witnesses (deterministic harvest **or** ≥2 votes), mandatory
entailment, and human sign-off; low-materiality takes the cheap path.

### LH6 / LH10 / LH11 — briefly

**LH6:** "the document says X in §3 and Y in §4" is not a pipeline bug, it is a finding for the policy
owner. Separate the two classes; the source-defect report is a deliverable.
**LH10:** the policy distinguishes verbatim-required language from paraphrase-permitted (§6). That
changes the grading mode downstream — carry `GENERATION_ALLOWED` through to the evaluator.
**LH11:** `proofloop`'s `GeometricJudge` hard-requires the licensed harness despite the open-core
claim. Do not plan to reuse it; build behind the same interface.

---

## 2. Provenance

Three linked records, all stored as triples so provenance is queryable in the same store.

### 2.1 The model

```
Triple   WAS_GENERATED_BY   Activity
Triple   WAS_DERIVED_FROM   Triple | Passage
Activity USED               Passage | Triple
Activity PERFORMED_BY       Agent          (model id + params, or human id)
Activity AT_BUILD           Build
Activity HAS_REASON         literal
Build    HAS_IDENTITY       literal        (corpus · schema · prompts · model · extractor)
```

Activities are the pipeline's own operations: `deterministic_harvest`, `glossary_harvest`,
`llm_extract`, `diagram_read`, `diagram_synthesise`, `entailment_check`, `canonicalise`, `merge`,
`conflict_resolve`, `human_edit`, `alias_apply`, `supersede`.

### 2.2 Why it earns its place — three payoffs

1. **Replay.** "Why is this triple in the graph?" resolves to a chain: admitted triple → merge of
   three candidates → each candidate's extraction activity → model and prompt version → passage →
   quoted span → document and location. Every step attributable.
2. **Blast radius.** §4 of the policy changes → which triples derive from those passages → which
   assertions compile from them → which scenarios use those assertions → which past verdicts are now
   stale. Policy-change impact analysis is *only* computable if derivation is recorded; without it,
   every policy edit forces a full re-run and full re-review.
3. **Audit.** verdict → assertion → rule triple → derivation → evidence span → source document. That
   is the chain a model-risk reviewer asks for, end to end.

### 2.3 Provenance consistency as a measured metric

Borrowed directly from the book's capstone, which reports it as a ratio: **every value-bearing triple
must cite a span that actually contains the value.** Deterministic to check — parse the value out of
the cited span and compare. Report it as a number per build, per relation family. A threshold triple
whose span does not contain the threshold is a defect regardless of how plausible it looks.

Second metric, same spirit: **span-level resolution** — what fraction of claims resolve to a
sentence-level span rather than a whole table or section. Coarse provenance is weak provenance.

### 2.4 Cost

Provenance roughly doubles the store's row count. It is worth it, and it is why the store is
file-backed and sorted (plan 01 §11.3) — provenance triples compress well, diff cleanly, and are
almost never queried interactively.

---

## 3. The build plan

Phase 1 only: documents in, a defensible triple graph out. Effort bands are relative
(S ≈ 1–2 days, M ≈ 3–5, L ≈ 1–2 weeks) and assume one engineer.

### Critical path

```
WP0 → WP1 → WP2 → WP3 → WP4 → WP5 → WP6 → WP7 → WP8 → WP9 → WP10 → WP11 → WP14
                                  └→ WP12 ─────────────┘        WP13 ┘
```

WP3 lands before any extractor exists, so every extractor is measurable from its first commit.

| WP | Scope | Deliverable | Acceptance criteria | Dep | Size |
|---|---|---|---|---|---|
| **WP0** | Repo scaffold | `pyproject.toml`, `src/metric/` skeleton, ruff + mypy strict + pytest, CI workflow | CI green on an empty test suite; `mypy --strict` clean | — | S |
| **WP1** | Ontology schema | `schemas/core.ontology.yaml`, `ontology/{schema,types,ids,validate}.py` | core + extension load and merge; a relation violating its signature is rejected; entity ids are stable across processes and machines; presence is never required | WP0 | M |
| **WP2** | Provenance + store | `store/{triples,evidence,build}.py`, `ontology/provenance.py` | a triple round-trips with evidence + derivation; build identity computed from the five-part tuple; atomic promotion — an interrupted build leaves no partial store | WP1 | M |
| **WP3** | Harness + fixtures + injectors | `tests/test_reproducibility.py`, `tests/fixtures/card_auth/`, `extract/faults/` | two runs over the fixture diff to Jaccard 1.0; ≥8 fault injectors each proven to trip their detector (detectors may not exist yet — the test is `xfail` until the WP that adds them) | WP2 | M |
| **WP4** | Corpus layer | `corpus/{manifest,readers/,furniture,passages,redaction}.py` | PDF/DOCX/XLSX/MD/image read; repeated furniture stripped; passage ids stable; a table's header travels with every row passage; a no-text-layer PDF is refused with a reason; redaction runs before any egress | WP1 | L |
| **WP5** | Deterministic harvest | `extract/deterministic.py` | on the fixture, recovers every numeric constraint and modal statement without an LLM; 100% reproducible by construction | WP4 | M |
| **WP6** | LLM layer | `llm/{gateway,structured,determinism,prompts}.py` | schema-constrained output with enum'd relations; malformed output repaired once then dropped and logged; prompt library hashed; n-vote helper; no call path bypasses `llm/` | WP1 | M |
| **WP7** | Batching + glossary | `extract/{batching,glossary}.py` | boundaries are a pure function of structure; no split mid-sentence/row/list-item; overlap present; **shuffling batch order produces an identical glossary** | WP4, WP6 | M |
| **WP8** | Extraction pass B | `extract/triples.py`, `extract/validators/` | every candidate carries a locatable quote; signature/cardinality/polarity/modality validators run; a batch yielding nothing triggers exactly one targeted re-read | WP7 | L |
| **WP9** | Admission gate | `admit/{grounding,entailment,gate,quarantine}.py` | criteria applied in order; every rejection recorded with its failing criterion; entailment calibrated on a labelled cohort before it gates anything; injected fabricated quote is discarded | WP8 | M |
| **WP10** | Canonicalisation | `resolve/{canonical,entities,lexicon,merges}.py` | the fixture's three phrasings of the attempt limit collapse to one triple with three evidence spans; **no merge across entity types is possible**; merges logged and reversible; learned aliases are proposals | WP9 | L |
| **WP11** | Reconciliation loop | `reconcile/{dedup,conflicts,integrity,paths,decisions,loop}.py` | dedup → conflict → integrity ordering; path-level model checking (LH5); loop is monotonic and terminates by no-change on the fixture; every decision logged and content-keyed (LH8) | WP10 | L |
| **WP12** | Diagram reading | `extract/diagrams.py` | three-pass read; the fixture's flowchart yields the same backbone as the prose; **disagreement raises a review item rather than merging** (LH1) | WP6, WP8 | M |
| **WP13** | Reports | `reports/` | coverage, quarantine, conflicts, open questions, provenance consistency, source-defect report (LH6), telemetry drift | WP11 | M |
| **WP14** | Accuracy gate | `tests/test_accuracy.py`, `reports/selfcheck.py` | self-answering precondition at 1.0 on the fixture; precision/recall reported per relation family against the independent annotation (LH1, LH2) | WP11, WP13 | M |
| **WP15** | CLI | `cli.py` | `ingest`, `validate-schema`, `report`, `reproduce` — each runnable on the fixture end to end | WP13 | S |

### Phase 1 exit criteria

Not "the code runs" — these are the conditions under which the graph is trustworthy:

1. **Stability** — two builds over the golden corpus are byte-identical in admitted triples.
2. **Accuracy** — self-answering precondition 1.0; precision and recall reported per relation family
   against independent annotation, with agreed thresholds.
3. **Detection** — every catalogued failure mode has an injector, and the detection rate is reported.
4. **No silent loss** — every rejected candidate is in quarantine with a reason; every unanswered
   question is in the open-questions report.
5. **Provenance** — every admitted triple resolves to source text and to the activities that produced
   it; provenance consistency reported as a number.
6. **Durability** — a second ingestion after a policy edit preserves every human decision whose
   underlying text is unchanged, and re-queues the rest.
7. **Honest gaps** — the fixture's `transfer_to_ccp` → `FAILED` outcome appears with no destination
   and an open question, and no invented state.

Criterion 7 is the one to watch. It is the cheapest thing to accidentally "fix" and the clearest
signal that the pipeline is doing its job rather than flattering itself.

### What is explicitly not in phase 1

Views (phase 2), reverse binding and turn-level ground truth (phase 3), scenario generation (phase 4),
the evaluator (phase 5), any GMS-backed semantics (phase 6, evidence-driven). `semantic/oracle.py`
ships in phase 1 as an interface with a baseline implementation only where LH4 requires one.

---

## 4. Decisions still blocking the start

WP0 can begin regardless. These block the WPs named.

| Decision | Blocks | Recommendation |
|---|---|---|
| Store: file-backed vs Neo4j | WP2 | file-backed as truth; graph store for querying. Makes the reproducibility diff a `git diff`. |
| SafeChain still the gateway; does it expose a seed? | WP6 | needed before determinism controls can be written honestly |
| Flask 1.x / internal mirror constraint | phase 2 | not blocking now |
| Who annotates the golden corpus | WP14 | must not be whoever writes the prompts (LH1) |
| Entailment model | WP9 | different provider from the extractor if available |
| Materiality tiering owner | WP9/WP10 | MRMG rules on what counts as high |
