# Design Plan 02 — The Ingestion Pipeline

**Status:** proposal for review. Supersedes §2–§4 of plan 01.
**Goal, restated:** a graph that is *complete* with respect to the source documents, has no
duplicates, no conflicts, and makes logical sense — reproducibly.

---

## 0. Corrections to plan 01

| Plan 01 said | Now |
|---|---|
| Extraction runs one LLM pass per relation family | **Batch by content size.** One call per batch returns every triple in that batch, any relation. §3 |
| Closed, hardcoded relation vocabulary | **Versioned, human-editable schema file.** Constrained at extraction time, editable between builds. §2 |
| Fixed entity type list | **Structural types fixed, domain types open.** Use cases declare their own. §2.1 |
| — | Nothing requires an entity or relation to be *present*. Validation is well-formedness, never presence. §2.3 |

---

## 1. The principle that governs everything below

> **Completeness is measured, never manufactured.**

The pipeline's job is to extract everything the documents assert and to *report* what they do not.
It must never close a gap by inventing a node. The working policy document (`grounding/07`) contains
a live example: `transfer_to_ccp` is declared to return `FAILED`, and no section says where that
leads. The correct output is an `Outcome` with no `LEADS_TO` and an open question — **not** a
fabricated fallback state. A pipeline that invents the state scores better on graph-completeness
metrics and is worse at its job.

Everything in §5–§7 follows from this: we detect incompleteness loudly rather than resolving it
quietly.

---

## 2. Schema: constrained at extraction, editable between builds

The tension in the brief is real — *"cannot run wild"* against *"not rigid, editable, varies by use
case."* They resolve on a time axis:

- **At extraction time** the LLM is hard-constrained to whatever the active schema declares. It
  cannot invent a relation; the structured-output enum makes it mechanically impossible.
- **Between builds** the schema is a plain YAML file a human owns, edits, versions and reviews.

So the vocabulary is closed *for any given build* and open *across* builds. The schema version is
part of the build identity (§8), so a schema edit is a visible, diffable, attributable change.

### 2.1 Two classes of entity type

| Class | Fixed? | Types | Why |
|---|---|---|---|
| **Structural** | semantics fixed by the pipeline | `Capability` `State` `Decision` `Outcome` `Action` `Tool` `Turn` `Rule` `Condition` `StateVariable` `Value` `Persona` `EvidenceSpan` | The pipeline reasons about these: it walks `State`s, compiles `Rule`s into assertions, evaluates `Condition`s. Their meaning cannot be use-case-specific or nothing downstream works. |
| **Domain** | open | anything the use case declares — `Customer`, `Card`, `Dispute`, `Account` | The pipeline never reasons about these; it only records and links them. |

A use case declares its domain types in its own schema extension. Structural types are inherited from
the core schema and may be *extended* (a new `Rule` subtype) but not redefined.

### 2.2 Relations: core set plus extensions

The core relation set from plan 01 §2.3 stands as the **default**, shipped as
`schemas/core.ontology.yaml`. Each relation declares its signature:

```yaml
relations:
  - name: HAS_NEXT_STEP
    domain: [State]
    range:  [State]
    cardinality: many
    description: the interaction may move directly from the domain state to the range state
    inverse: PRECEDED_BY

  - name: RULE_FORBIDS
    domain: [Rule]
    range:  [Action, Outcome, State]
    cardinality: many
    polarity: negative          # drives the polarity check in §5.C3
    description: the rule prohibits the range entity
```

A use case adds `schemas/<use_case>.ontology.yaml`, which may **add** relations and domain types, and
**narrow** (never widen) the signature of a core relation. The validator loads core + extension and
resolves conflicts by refusing to start, not by precedence — a use case that contradicts core is a
schema bug.

### 2.3 Presence is never required

Validation checks **well-formedness**, never presence. There is no rule that says "a use case must
have Decisions." Every completeness check is conditional:

- *if* a `Decision` exists, it has ≥2 `Outcome`s
- *if* an `Outcome` exists, it either `LEADS_TO` something or its parent state is terminal
- *if* a `Condition` exists, its variable is declared and its comparison value resolves

A batch agent with no conversational turns, or a use case with no tools, is valid.

### 2.4 The proposal channel

When extraction repeatedly encounters a relation the schema cannot express, we want to know. The
extractor may emit a **proposed** relation into a separate stream: never used, never admitted to the
graph, logged with the evidence that motivated it and a frequency count. A human promotes it into the
schema, or doesn't. This is how the vocabulary stays exhaustive over time without the LLM widening it
at runtime.

---

## 3. Batching by content size

One call per batch; the batch returns every triple it finds, of every type.

**Batch construction** (deterministic):
- Target a token budget, not a character count — character-count batching truncates unpredictably
  across formats.
- **Never split mid-unit.** Boundaries are allowed at headings, paragraph breaks, list-item breaks and
  table-row breaks; never mid-sentence, mid-row or mid-list-item.
- **Overlap** by one unit on each side. A rule split across a boundary ("The bot may make up to 3
  total authentication attempts. | It must not make a fourth attempt.") is otherwise extracted
  without its subject.
- Tables are a batch unit: a table travels with its header, always.
- Each batch carries a **context header**: document title, the heading path to this batch, and the
  frozen glossary (§3.1). Deterministic, derived from structure.

### 3.1 The order-dependence trap, and the two-pass fix

The obvious design — accumulate an entity glossary as batches are processed, feed it forward — is
wrong twice over. Batch *N*'s extraction would depend on batches 1…*N*−1, so (a) reordering the
corpus changes the graph, killing reproducibility, and (b) an error in an early batch propagates into
every later one.

**Fix: two passes, both order-independent.**

1. **Pass A — glossary harvest.** Every batch is read independently for *entity mentions only*
   (surface form + candidate type + evidence). No relations. Results merged by set union, canonicalised
   (§4), and **frozen**.
2. **Pass B — triple extraction.** Every batch is read with the *complete, frozen* glossary in its
   context header. Every batch sees the same glossary regardless of position.

Pass A is cheap (narrow task, small output). Pass B gets full-document entity context without any
sequential dependency. Both passes are embarrassingly parallel and their results merge commutatively.

### 3.2 What we lose by not prompting per relation family, and how we recover it

Per-family prompting would have given sharper precision per relation. Batching by content gives
better **recall and coreference** — the model sees the whole local context once — at some cost in
per-relation precision. We recover the precision after the fact, where it is cheaper and testable:

- **Per-family validators** run over the extracted triples (signature checks, polarity checks,
  cardinality checks, condition resolvability). A validator is deterministic code and can be unit
  tested; a prompt cannot.
- **Targeted re-read**, not a re-prompt of everything: if a batch yields no triples at all, or a
  family-specific check fails, that *specific* batch is re-read once with a narrowed instruction. One
  bounded retry, logged.

---

## 4. Where this pipeline breaks

The failure catalogue. Stage by stage: what goes wrong, why it is dangerous, how we detect it, what
we do about it. Failures marked **silent** produce a plausible-looking graph and are the ones worth
engineering against.

### A. Source and parse

| # | Failure | Danger | Detection | Mitigation |
|---|---|---|---|---|
| A1 | Scanned PDF, no text layer | **silent** — reads as empty, contributes nothing | text-density check per page | refuse the file with a reason; ask for a text-based copy |
| A2 | Table structure lost; header detached from rows | **silent and high-impact** — "3 attempts" binds to the wrong subject | header/row arity check; cell-count variance | structure-aware table reader; header repeated on every row passage; tables never split |
| A3 | Multi-column PDF read in column-crossing order | **silent** — false adjacency invents relations | reading-order heuristics vs layout boxes | layout-aware extraction; flag pages where order confidence is low |
| A4 | Running headers/footers interleaved into body ("Card Authentication Voice Bot • 1") | pollutes quotes, breaks span verification | repeated-line detection across pages | strip repeating furniture before passaging |
| A5 | Hyphenation, ligatures, smart quotes | **false rejection** of correct extractions at quote verification | verification failure rate spike | normalise for matching but keep the original for display — the old `grounding.py` already does exactly this |
| A6 | Same content in two documents (policy + summary deck) | duplicate facts with different evidence | canonical-form hash collision across doc ids | merge, keep both evidence spans; never drop provenance |
| A7 | Two policy versions in one corpus | direct contradiction | version metadata in the manifest | **declared** precedence by effective date; superseded triples marked, not deleted |
| A8 | Diagram carries structure absent from prose | under-extraction if images are skipped | image inventory vs diagram-derived triple count | vision pass is mandatory when images exist, not optional |

### B. Batching

| # | Failure | Danger | Detection | Mitigation |
|---|---|---|---|---|
| B1 | Rule split across a boundary | dangling or mis-attributed rule | subject-less rule detector (a `Rule` with no `GOVERNED_BY`) | structure-aware boundaries + one-unit overlap (§3) |
| B2 | Cross-batch coreference ("it must not…") | **silent** — resolves to the wrong subject | pronoun-initial passage detector | frozen glossary + heading path in the context header |
| B3 | Glossary accumulated in order | reproducibility loss + error propagation | reproducibility harness (§8) catches it as drift | two-pass design (§3.1) |
| B4 | Batch exceeds output budget; tail truncated | **silent recall loss** | output JSON completeness check; last-passage-covered check | token-budgeted batches; assert every passage id in the batch appears in the coverage map |
| B5 | Overlap causes the same triple twice | benign duplicate | set union on canonical key | idempotent merge; overlap is safe by construction |

### C. Extraction

| # | Failure | Danger | Detection | Mitigation |
|---|---|---|---|---|
| C1 | Hallucinated triple | **silent** | mandatory verbatim quote + span location | discard on failure to locate (`grounding.py`) |
| C2 | Fabricated quote | **silent** | exact span match against the passage | discard |
| C3 | **Quote is real but does not support the triple** | **silent, and not caught by span verification** — this is the gap in the old design | entailment check: does this span support this triple? | second cheap pass (NLI classifier or narrow LM call) over LLM-derived triples; mandatory above a materiality bar, sampled below |
| C4 | **Polarity inversion** — `RULE_REQUIRES` where the text forbids | **the most dangerous single error**: well-formed, meaning inverted | negation-marker scan on the quote vs the relation's declared `polarity`; disagreement → review | dedicated polarity validator; the schema declares polarity per relation (§2.2) so this is checkable |
| C5 | Under-extraction — a fact simply not emitted | **silent, and invisible by construction** | **passage coverage audit**: every passage yields ≥1 triple or is explicitly classified non-normative | the audit turns invisible recall loss into a reviewable list; deterministic harvest sets a floor; n-vote **union** raises recall |
| C6 | Over-extraction — narrative order read as `HAS_NEXT_STEP` | invents workflow edges | cross-check prose-derived backbone against diagram-derived backbone | disagreement between the two readings is a review item, not an auto-merge |
| C7 | Modal strength mis-read ("should" as "must") | wrong severity | modal-term scan vs assigned severity | severity derived from the modal term deterministically where one is present |
| C8 | Implicit facts never stated as entities | under-extraction of real structure | rules referencing an undeclared outcome | e.g. "treat unclear input as unsuccessful" implies an `UNCLEAR` outcome → raise as an open question, do not invent silently |
| C9 | Scope leakage — a global rule attached to one state | too narrow, or too broad | scope declared per rule + heading-path evidence | rules from a global section default to journey scope unless the text names a state |

### D. Canonicalisation and entity resolution

| # | Failure | Danger | Detection | Mitigation |
|---|---|---|---|---|
| D1 | **Over-merge** — `transfer_to_ccp` (tool) merged with `transfer` (state) | **worse than under-merge**: silently destroys structure, and the loss is unrecoverable downstream | type-equality precondition; merge log review | **never merge across entity types**; require name similarity *and* type equality *and* non-contradictory evidence; every merge logged and reversible |
| D2 | Under-merge | duplicates survive | duplicate detector (§6) | alias cascade; surfaced as a merge proposal rather than silently left |
| D3 | Uncalibrated similarity threshold | arbitrary merges | precision/recall on a labelled entity-pair set | threshold calibrated on a labelled cohort before use; until then, propose-only |
| D4 | **Alias-table poisoning** — a bad merge learned in build *N* makes build *N+1* deterministically wrong | **silent, and compounding**: reproducibility makes the error stable, which reads as correctness | alias provenance and review state | aliases learned in a build are **proposals**; only human-approved aliases are authoritative in later builds |

### E. Conflict handling

| # | Failure | Danger | Detection | Mitigation |
|---|---|---|---|---|
| E1 | False conflict from a duplicate (same fact, two phrasings) | noise drowns real conflicts | dedup runs *before* conflict detection | ordering of the loop (§7) is deliberate |
| E2 | Missed conflict — the two triples never share a canonical key | **silent** | canonical form for constraints (§6.1) | numeric/deontic facts normalised to a comparable form before comparison |
| E3 | Auto-resolution picks the wrong side | **silent** | — | conflicts are never auto-resolved except by *declared* precedence (§A7); everything else queues for a human |
| E4 | Version conflict mistaken for contradiction | wrong triple dropped | document version metadata | precedence is declared in the manifest, not inferred |

### F. Reproducibility

| # | Failure | Danger | Detection | Mitigation |
|---|---|---|---|---|
| F1 | Provider changes the model behind a stable name | drift with no local cause | model fingerprint recorded in the manifest; harness diff | pin model ids with version suffixes where the provider exposes them; treat drift as a build-breaking change |
| F2 | Non-determinism at temperature 0 (batching, MoE routing) | small residual drift | harness reports Jaccard < 1.0 | n-vote consensus for high-materiality families; record vote counts as confidence |
| F3 | Iteration order leaking into prompts | drift | harness | sorted-by-stable-id everywhere; no set/dict iteration into prompt text |
| F4 | Retry paths differing between runs | drift | retry log in the manifest | bounded, deterministic retry prompts |

### G. Operational

| # | Failure | Danger | Mitigation |
|---|---|---|---|
| G1 | Partial failure mid-run | half-written store read as complete | build to a scratch location, promote atomically on success — the old repo's `_accept_if_better` discipline generalised |
| G2 | PII reaching a model | compliance | redaction before any model call, per-file override honoured |
| G3 | Cost/time on a large corpus | unusable | deterministic harvest first; parallel batches; per-stage call accounting |

---

## 5. Admission: a triple is not in the graph until it earns its place

Borrowing the book's functionality check and making it structural. Extraction produces **candidates**;
the graph contains **admitted** triples. Admission is a gate with named criteria:

```
candidate
  → schema valid          (types, signature, cardinality)
  → quote located         (grounding.py)
  → quote supports claim  (entailment, §C3)
  → polarity consistent   (§C4)
  → canonicalised         (§4)
  → not in unresolved conflict
  → ADMITTED
```

Anything failing lands in **quarantine** with the failing criterion, the candidate, and its evidence.
Quarantine is a first-class output, not a log line — it is how "what did the pipeline throw away, and
why" gets answered, and it is the fastest way to find a broken extractor.

---

## 6. Three detectors for the three goals

### 6.1 No duplicates — canonical form, not text

Deduplication on surface text fails the moment the same fact is stated twice differently. The working
policy states one constraint three ways: *"maximum of 3"*, *"up to 3 total"*, *"must not make a
fourth attempt"*. All three must reduce to one fact.

So every constraint-bearing triple is reduced to a **canonical form** before comparison:
`(subject_entity_id, constraint_kind, operator, normalised_value, scope)` — here
`(authenticate_customer, attempt_limit, lte, 3, journey)` for all three phrasings. Duplicates collide
on that key; the surviving triple carries all three evidence spans.

The same treatment for deontic facts: `(scope, modality, action_entity_id)` so a prohibition stated in
§3B and again in §4 merges to one `Rule` with two evidence spans.

### 6.2 No conflicts — typed detectors over canonical keys

Structural, deterministic, each a small testable function:

- one `Outcome` with two different `LEADS_TO` tails
- a `State` both `IS_TERMINAL=true` and carrying `HAS_NEXT_STEP`
- two `VALUE_IS` for one canonical key with different values
- `RULE_REQUIRES` and `RULE_FORBIDS` over the same `(scope, action)`
- a `Condition` on an undeclared variable
- a `Turn` whose actor contradicts its parent state's declared actor

Semantic conflicts (stance reversals) use the `SemanticOracle` interface, and their verdicts are
**proposals for review**, not admissions.

### 6.3 Logical sense — walkability and integrity

Conditional checks (§2.3), run as graph queries:

reachability from a start state · every outcome lands somewhere or is declared terminal · no decision
with a single outcome · every rule attached to ≥1 scope entity · every condition resolvable · every
tool with ≥1 outcome · no orphans · no cycles without a bounding retry limit.

Each failure becomes an **open question** in the old repo's format — the question, what it blocks, and
the evidence around it — because that pattern already works and a person can answer it in a sitting.

---

## 7. The reconciliation loop

Order matters, and it is not arbitrary:

```
dedup  →  conflict detect  →  integrity check  →  (changed? repeat)
```

Dedup first, or duplicates masquerade as conflicts (E1). Integrity last, because merges and conflict
resolutions change the graph shape.

**Termination and oscillation.** A naive fixpoint loop can oscillate — merge A into B, a later pass
splits them, the next merges again. Two constraints prevent it:

1. **Monotonicity within a run.** A pass may only add resolutions. No pass may undo a decision made
   earlier in the same run; reversals are a human action between runs.
2. **A decision log.** Every merge, conflict verdict and drop is recorded with its reason. A decision
   already in the log is never re-litigated within the run, which makes the loop idempotent.

Bounded pass count, and terminating by "no change" rather than by exhausting the bound is itself a
health signal worth reporting.

---

## 8. Reproducibility, revisited for content batching

Build identity is the tuple:
`(corpus manifest hash, schema version, prompt library hash, model id + params, extractor version)`.

Same tuple must mean the same graph. The **reproducibility harness** runs ingestion twice over a
fixed corpus and diffs admitted triples, reporting Jaccard plus added/dropped by relation family.
Target 1.0; any drift is a defect with a named cause.

Content batching adds two specific requirements beyond plan 01: batch boundaries must be a pure
function of document structure (never of a token count that shifts with a parser upgrade), and the
glossary must be frozen before pass B (§3.1).

**Build the harness first.** It is the only thing that can tell us whether any of the above actually
works, and writing it after the extractors means shipping extractors we cannot evaluate.

---

## 9. What we take from eval-poc, concretely

| eval-poc | What we take | What we change |
|---|---|---|
| `Rule` as a graph node with `code/statement/rule_type/subject/predicate/object/polarity` | the modelling — this is the right shape, and `polarity` is exactly what §C4 needs | promoted to first-class triples with evidence and severity |
| `RuleCompiler` registry: one function per rule code, unknown codes → WARNING "uncompiled" assertion | **the fallback behaviour is the valuable part** — a rule that cannot be compiled is never silently dropped | the registry becomes declarative (rule kind → assertion template) rather than domain-specific Python, which is its stated limitation |
| `GroundTruthAssertion` with `category/predicate/severity/source_rule_id/source_step_id/expected_value` | the assertion record shape, near-verbatim | adds evidence span and derivation level |
| `GraphValidator` collecting **all** issues before raising | the discipline: never raise on the first problem | extended to the checks in §6.3 |
| `condition_holds` parsing `NEXT.when` with two regexes | the idea that transition conditions must be *executable* | conditions become structured (`ON_VARIABLE`/`OPERATOR`/`COMPARE_TO`), so no regex scraping |
| `provenance.stamp` writing oracle + KG version onto ground truth | build identity on every artifact | extended to per-triple provenance |
| `PathResolver` hardcoding `step_id == "authentication"` | — | the one thing not to copy; it is the seam where the generic design leaked into the domain |

## 10. What the book's open repo gives us

`knowlytix/beyond-ship-and-pray` is Apache-2.0 and is the **evaluation layer only** — DoE suites,
fault injection, trajectory metrics, groundedness, the judge interface. `proofloop/evaluation/
groundedness.py` describes itself as "a deliberately naive baseline." **There is no ingestion, no
triple extraction and no GEODE in the open repo**; that lives in the licensed `knowlytix` backend.

So: the ingestion pipeline is ours to build. What the repo does give us, and what we should copy, is
the **open-core seam** — `gms.available()`, with gates and judges behind one interface so the GMS
implementation is a drop-in that changes no call sites. That is precisely the `SemanticOracle`
boundary from plan 01 §8.1, now with a reference implementation to follow.

Their evaluation layer is also directly reusable later (phases 4–5) rather than reimplemented.

---

## 11. Build order for phase 1

1. **Schema** — core ontology YAML, signatures, loader, validator, extension mechanism.
2. **Reproducibility harness** — before the extractors it measures.
3. **Deterministic layer** — readers, furniture stripping, structure-aware passaging, manifest,
   redaction, deterministic harvest.
4. **Batching** — structure-aware boundaries, overlap, context headers, pass-A glossary.
5. **Extraction** — pass B, schema-constrained, quote-bound; then the validators of §C.
6. **Admission gate + quarantine.**
7. **Canonicalisation** — cascade, alias proposals, merge log.
8. **Reconciliation loop** — dedup, conflict, integrity, decision log.
9. **Freeze, version, reports** — triples, evidence, quarantine, conflicts, open questions,
   reproducibility, coverage.

The working policy document (`grounding/07`) is the golden fixture: small enough that the correct
graph can be written by hand and asserted against, and it exercises table parsing, a diagram/prose
cross-check, three phrasings of one constraint, a prohibition in two scopes, an implicit outcome, and
a genuine gap that must be reported rather than filled.
