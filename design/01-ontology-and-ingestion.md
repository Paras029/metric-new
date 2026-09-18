# Design Plan 01 — Triple Ontology and the Ingestion Pipeline

**Status:** proposal for review. Nothing here is built yet.
**Partially superseded:** §2 (ontology) and §3–§4 (ingestion, reproducibility) are replaced by
[plan 02](02-ingestion-pipeline.md), which makes the schema human-editable rather than hardcoded and
batches extraction by content size rather than by relation family. §5 (views), §6 (reverse
ingestion), §7 (OTEL), §8 (GMS) and §9–§11 still stand.

**Scope:** the ontology schema, the forward ingestion pipeline (documents → triples), the correction
loops, the views, and the reverse pipeline (conversation → ground truth). Plus two decisions that
need settling: GMS in phase 1, and how scenarios are generated without it.

**Premise:** `metric-new` starts clean. We borrow ideas and specific well-tested components from the
old Scenario Generator, the eval-poc, and the *Beyond "Ship and Pray"* methodology — but the target
artifact changes. We are no longer filling a CDS/intake spreadsheet. We are building a **versioned,
evidence-grounded triple store** that is simultaneously: the policy representation, the scenario
source, and the ground-truth oracle for observed conversations.

---

## 1. The core shift

| | Old Scenario Generator | metric-new |
|---|---|---|
| Policy representation | 6-sheet Excel intake (L1–L4, Personas, Tools) | versioned triple store |
| Schema enforcement | column positions | closed relation vocabulary + validator |
| Normative rules | **absent** | first-class `Rule` entities with deontic relations |
| Runtime state | **absent** | `StateVariable` entities with typed conditions |
| Provenance | evidence spans stop at the intake draft | every triple carries an evidence span |
| Entry points | scenario generation only | forward (docs → triples) **and** reverse (conversation → ground truth) |
| Telemetry | none | OTEL symbols bound into the ontology |

One sentence: **the knowledge graph becomes the single shared artifact that policy, scenarios,
conversations and ground truth all resolve against.**

---

## 2. The ontology

### 2.1 Why a closed vocabulary is the load-bearing decision

The instruction "it cannot run wild" is satisfied by exactly one mechanism: **the LLM is never
allowed to invent an entity type or a relation.** Both are enumerations in a versioned schema, passed
into structured output as enums, and enforced by a validator that rejects anything outside them.
Everything else in this plan — reproducibility, conflict detection, reverse binding — depends on this
being true.

### 2.2 Entity types

| Type | What it is |
|---|---|
| `UseCase` | root; one agent/journey under review |
| `Capability` | a coherent thing the agent can do (maps to a workflow span) |
| `State` | a position the interaction can occupy, including terminal ones |
| `Decision` | a branch point |
| `Outcome` | a named result of a decision or tool (closed per parent) |
| `Action` | something the agent does: say, ask, call, escalate, terminate |
| `Tool` | an external operation |
| `Turn` | a conversational slot: actor + purpose |
| `Rule` | a normative statement — obligation, prohibition, permission, constraint |
| `Condition` | a structured predicate |
| `StateVariable` | a typed runtime variable (counter, flag, checkpoint) |
| `Value` | an exact typed value — threshold, limit, amount, enum member |
| `Persona` | a kind of user |
| `Concept` | a domain noun (card, dispute, account) |
| `EvidenceSpan` | a located, quoted anchor in a source document |

Entity IDs are **deterministic**: `id = type_prefix + "-" + sha1(type + ":" + canonical_name)[:10]`.
Not LLM-chosen, not a counter that depends on arrival order. Same concept, same document set, same
ID — every time.

### 2.3 The closed relation vocabulary

Grouped by family. This is the full set; extending it is a schema version bump with a migration, not
an ad-hoc addition.

**Structure / workflow** — the backbone the workflow view renders
```
UseCase      HAS_CAPABILITY        Capability
UseCase      STARTS_AT             State
Capability   HAS_STATE             State
State        HAS_NEXT_STEP         State          ← primary workflow edge
State        OFFERS_DECISION       Decision
Decision     HAS_OUTCOME           Outcome
Outcome      LEADS_TO              State
State        HAS_OUTCOME_TYPE      literal(Happy path|Retry|Fallback|Escalation|Termination)
State        IS_TERMINAL           literal(true|false)
```

**Action / tool**
```
Decision     USES_TOOL             Tool
Capability   USES_TOOL             Tool
Tool         RETURNS               Outcome
Tool         IS_STATE_CHANGING     literal(true|false)
State        REQUIRES_ACTION       Action
Action       INVOKES               Tool
```

**Conversation**
```
State        HAS_TURN              Turn
Turn         HAS_ACTOR             literal(BOT|CUSTOMER|SYSTEM)
Turn         EXPECTS_OUTCOME       Outcome
Turn         HAS_CANONICAL_TEXT    literal
Turn         GENERATION_ALLOWED    literal(true|false)
```

**Normative / deontic** — the layer the old code lacks entirely
```
State|Decision|Tool|Turn|Capability   GOVERNED_BY      Rule
Rule         RULE_REQUIRES         Action|Outcome|State
Rule         RULE_FORBIDS          Action|Outcome|State
Rule         RULE_PERMITS          Action
Rule         RULE_STATES           literal(the rule text as written)
Rule         HAS_CONDITION         Condition
Rule         HAS_EXCEPTION         Condition
Rule         HAS_SEVERITY          literal(blocker|error|warning|info)
Rule         HAS_SCOPE             literal(turn|state|capability|journey|tool)
Rule         PRECEDES              Action|State        (sequence rules)
```

**Conditions, variables, exact values**
```
Condition    ON_VARIABLE           StateVariable
Condition    OPERATOR              literal(lt|lte|eq|neq|gte|gt|in|exists)
Condition    COMPARE_TO            Value
UseCase      HAS_STATE_VARIABLE    StateVariable
StateVariable VARIABLE_TYPE        literal(int|bool|enum|string)
Concept|Rule HAS_THRESHOLD         Value
Value        VALUE_IS              literal(typed, exact, hashed)
```

**Telemetry binding** — how the KG speaks OTEL (see §7)
```
Capability   EMITTED_AS_WORKFLOW   literal(workflow span name)
Tool         EMITTED_AS_TOOL       literal(span `tool` attribute)
Outcome      EMITTED_AS_RESULT     literal(e.g. "match=NO_PREFERENCE_SHARED")
State        EMITTED_AS_CHECKPOINT literal(e.g. "checkpoint=check14Key")
StateVariable EMITTED_AS_FIELD     literal(e.g. "no_user_pref_counter")
```

**Lexicon / provenance / versioning**
```
literal      ALIAS_OF              Entity
Entity       REFERS_TO             Concept
any triple   (carries) EVIDENCE    EvidenceSpan
EvidenceSpan IN_DOCUMENT           literal(doc id)
EvidenceSpan AT_LOCATION           literal(page/sheet/char range)
EvidenceSpan QUOTES                literal(verbatim text)
Entity|Rule  SUPERSEDES            Entity|Rule
Entity|Rule  VERSION_OF            literal(policy version)
```

~40 relations. Every one has a declared (head type → tail type) signature; the validator enforces the
signature, so `Rule HAS_NEXT_STEP Tool` is rejected structurally rather than debated.

### 2.4 Every triple is an assertion record, not a bare edge

```
Triple:
  head_id, relation, tail_id_or_literal
  evidence_span_ids: [...]         # ≥1 required, or extraction_method=human
  extraction_method: deterministic | llm | vision | human | derived
  confidence: float
  policy_version: str
  schema_version: str
  extractor_version: str
  vote_count: int                  # if n-vote consistency was used
  status: asserted | conflicted | superseded | pending_review
```

Provenance is not a nice-to-have — it is what makes a downstream evaluation verdict defensible to a
reviewer, and it is what `grounding.py` in the old code already gives us for free.

---

## 3. The ingestion pipeline

Eight stages. The design rule throughout: **anything that can be got deterministically is never asked
of a model.** Every LLM call is narrow, schema-constrained, and evidence-bound.

```
 0  Intake & manifest        files + sample OTEL → hashed corpus manifest
 1  Deterministic parse      → passages (stable IDs, structure-aware)
 2  Deterministic harvest    → candidate triples from regex/table/modal rules
 3  Diagram reading          → workflow triples (3-pass vision)
 4  Constrained LLM extract  → triples, one pass per relation family
 5  Canonicalisation         → entity resolution, alias capture
 6  Correction loops         → dedup · conflict · completeness (to fixpoint)
 7  Freeze & version         → triple store + evidence + lexicon + reports
```

### Stage 0 — Intake and manifest
Accept PDF, DOCX, PPTX, XLSX/CSV, MD/TXT, images (PNG/JPG), **and a sample OTEL trace export**.
Hash every file; the manifest (file hashes + schema version + prompt-library hash + model config) is
the identity of a build. Scanned PDFs with no text layer are refused with a reason, not read as empty
— the old code already behaves correctly here.

### Stage 1 — Deterministic parse to passages
Structure-aware readers per format. Tables are read row-wise with the header repeated on each
passage, because that is where thresholds live. A passage is
`{id, doc_id, location, kind: prose|table|list|heading|image, text}` with
`id = sha1(doc_id + location + normalised_text)[:12]`. PII redaction runs here — before any bytes
reach a model.

### Stage 2 — Deterministic candidate harvest (no LLM)
Regex and rule extraction of what is free: numerics with units, modal sentences (`must`, `must not`,
`may`, `shall`), bounded counts ("no more than three"), durations ("within 60 days"), enumerated
lists, `(key, value)` and `(condition, action)` table rows. These land as triples with
`extraction_method=deterministic, confidence=1.0`. **Every triple harvested here is one the LLM is
not asked for**, which is the cheapest reproducibility win available.

### Stage 3 — Diagram and workflow reading
The old code's three-pass approach is the best diagram handling we have; retarget its output from
intake sheets to triples:
1. each image alone → an explicit enumerated node/edge list (a box missed in a node list shows up as
   an arrow pointing at nothing; a box missed in prose vanishes silently)
2. all readings joined → one graph in ontology vocabulary
3. the joined graph checked against walkability properties; the *specific* failures put back to the
   images once, with the images still attached

Produces most of the `HAS_NEXT_STEP` / `OFFERS_DECISION` / `HAS_OUTCOME` / `LEADS_TO` backbone.

### Stage 4 — Constrained LLM extraction
**One pass per relation family, not one mega-prompt.** Workflow · rules · conditions & values ·
turns & actors · lexicon. Each pass:
- receives the closed vocabulary for *its* family only
- emits through a JSON schema whose `relation` field is an enum
- must attach a verbatim quote per triple
- is validated, and schema violations are retried once with a deterministic repair prompt, then dropped and logged

Triples whose quote cannot be located in the cited passage are **discarded, not flagged** — a
fabricated citation is worse than no citation. This is `core/grounding.py` from the old repo,
reused essentially as-is (tolerant of PDF mangling, intolerant of rewording).

### Stage 5 — Canonicalisation and entity resolution
Surface form → canonical entity by a strict cascade: exact match → alias table → deterministic
normalisation (case/punctuation/whitespace folding) → embedding similarity above a **calibrated**
threshold → otherwise a new entity. Every resolution is written back as an `ALIAS_OF` triple, so the
lexicon grows and the *next* build has less to infer. This is where "the same concept extracted twice
in different words" is resolved.

### Stage 6 — The correction loops
Three passes, run in order, iterating to fixpoint (bounded, every pass logged).

**6a — Duplicate and redundancy resolution**
- exact duplicates: set-union by `(head, relation, tail)`
- same `(head, relation)` with tails that canonicalise to one entity → merge
- near-duplicate entities (`auth_attempt` / `authentication_attempt`) → merge via the §5 cascade,
  merge recorded as `ALIAS_OF` so it is auditable and reproducible
- duplicate rules: two `Rule`s with identical `(subject, predicate, object)` but different statement
  text → merge, keep both statements as evidence

**6b — Conflict detection**
*Structural (deterministic):*
- one `Outcome` with two different `LEADS_TO` tails
- a `State` both `IS_TERMINAL=true` and carrying `HAS_NEXT_STEP`
- two different `VALUE_IS` for one key (fee = 35 and fee = 50)
- `RULE_REQUIRES` and `RULE_FORBIDS` over the same (scope, action)
- a `Condition` whose variable is never declared

*Semantic (LLM-assisted, deterministically adjudicated):* stance reversals — required vs optional,
permitted vs forbidden — the book's value-polarity check.

**Conflicts are never silently auto-resolved.** Three outcomes only: (i) a declared precedence rule
applies (later policy version supersedes), (ii) one re-read of the cited passages resolves it,
(iii) it becomes a first-class `Conflict` record in a human review queue. An unresolved conflict is a
representable state of the graph — that is deliberate.

**6c — Completeness and integrity** (deterministic, graph-shaped)
Every `Outcome` leads somewhere or is declared terminal · every `State` reachable from a start ·
every `Decision` has ≥2 outcomes · every `Rule` attaches to ≥1 scope entity · every `Condition`
resolves to a declared variable and value · every `Tool` has ≥1 outcome · every entity has ≥1
evidence span · no orphans. Failures become **open questions put to a human**, reusing the old
repo's `core/gaps.py` + open-questions pattern rather than inventing a new one.

### Stage 7 — Freeze and version
Emit: canonical sorted triple store · evidence store · lexicon · conflict list · open questions ·
build manifest · reproducibility report (§4) · telemetry drift report (§7).

---

## 4. Reproducibility — treated as a testable property, not an aspiration

The requirement was stated plainly: the same documents must produce the same graph. With an LLM in
the loop that only holds if it is engineered and then **measured**.

**Engineered:**
1. Greedy decoding (temperature 0), fixed seed where the gateway exposes one.
2. Deterministic chunking — stable passage IDs from content hashes, never from iteration order.
3. Deterministic prompt assembly — passages sorted by ID; no set/dict iteration leaking into prompts;
   no timestamps, no run IDs, nothing ambient.
4. Schema-constrained output with enum'd relations; bounded, deterministic repair on violation.
5. Deterministic entity IDs (§2.2) and order-independent merge (set union, sorted on write).
6. Optional **n-vote consistency** for high-materiality families: run extraction k times, keep
   triples appearing in ≥ m runs, store the vote count as confidence. This converts residual
   non-determinism from an invisible risk into a recorded number.

**Measured — the gate:**
A CI job runs ingestion twice over a fixed corpus and diffs the triple sets. Report Jaccard
similarity, plus the added/dropped triples by relation family. **Target 1.0; any drift is a defect
with a named cause, not noise to tolerate.** A build is identified by
`(corpus hash, schema version, prompt hash, model id + params, extractor version)` — same tuple must
mean same graph, and the harness is what proves it.

This harness is the first thing worth building, before the extractors it tests.

---

## 5. Views

### 5.1 Workflow view — the primary, readable view
Render only the `HAS_NEXT_STEP` / `OFFERS_DECISION` / `HAS_OUTCOME` / `LEADS_TO` subgraph, top to
bottom, from `STARTS_AT` to terminal states. Retry loops routed through a side lane as dashed edges —
the old `webapp/graphview.py` already does exactly this and it is the single reason the current graph
picture is readable at all; carry it over.

Each state node carries **badges** for what else attaches to it: rules (by severity), guardrails,
thresholds, required actions, declared variables. Hover or click expands them with rule statement +
evidence + source document. This is the layered readability described: workflow as the spine,
everything else as annotation on a node.

### 5.2 Triple view / editor
A filterable table of `(head, relation, tail, evidence, method, confidence, status)` with inline
editing validated against the closed schema. Human edits are recorded as `extraction_method=human`
with an audit trail — the current intake-editing UI is the reference for interaction, not for data
model.

### 5.3 Knowledge-graph view — and an honest recommendation on 3D
A 3D force-directed graph demos extremely well and, at this node count, reads worse than 2D. Depth
cues fight edge tracing, occlusion hides exactly the sparse structure you are trying to inspect, and
nothing is ever quite where you left it.

**Recommendation:** the workflow view is the working view. The KG view is 2D, layered by entity type,
with hard filtering by relation family / entity type / evidence status — that is what makes a triple
store inspectable. Keep 3D as an optional presentation mode for leadership and demos, where "this is
the shape of the policy" is the message and precise reading is not required. That is a real use, just
not the working one.

---

## 6. Reverse ingestion — conversation to ground truth

### 6.1 Formalising the "two of three" idea
The framing is exactly right and worth stating precisely: **the knowledge graph is a function from
`(head, relation)` to `tail`.**

- The observation supplies the **head** (where in the graph this turn is) and the **relation**
  (what kind of thing should happen next).
- The graph supplies the **tail** — that is the ground truth.
- The trace's *actual* tail is what gets graded against it.

So per turn: bind the position, ask the graph, compare. The bot's response is never the source of
truth — it is the thing being judged. That independence is the whole point, and it is preserved
structurally rather than by discipline.

### 6.2 The binding cascade — deterministic first
This is where OTEL earns its keep. From the sample trace, binding is mostly **lookup, not
inference**:

| Tier | Source | Mechanism |
|---|---|---|
| 1 — deterministic | workflow span name | → `Capability` via `EMITTED_AS_WORKFLOW` |
| | `set_metadata` `["checkpoint","check14Key"]` | → `State` via `EMITTED_AS_CHECKPOINT` |
| | tool span name | → `Tool` via `EMITTED_AS_TOOL` |
| | tool output `{"match": X}` | → `Outcome` via `EMITTED_AS_RESULT` |
| | tool input dict keys | → `StateVariable` values via `EMITTED_AS_FIELD` |
| 2 — lexicon | utterance surface forms | → entities via `ALIAS_OF` |
| 3 — semantic | whatever tiers 1–2 leave open | embeddings/LLM → **candidates + confidence**, never a silent single answer |

Binding confidence and alternatives are carried forward, not collapsed. A low-confidence binding
surfaces as evaluation uncertainty or routes to adjudication — it never hardens into a verdict.

### 6.3 What a turn produces
A turn-level ground-truth record: bound position (+ confidence + evidence) · expected action / tool /
outcome / next state · the rules in force at that position · the compiled assertions to check ·
provenance for every one. Per-turn, per-occurrence — repeated turns are distinct occurrences.

### 6.4 The three-way consistency
- **conversation ↔ KG** — the binding cascade
- **KG → ground truth** — assertions compiled from rules, carrying rule provenance
- **conversation ↔ ground truth** — the verdict

Every verdict traces back: turn → bound state → governing rule → evidence span → source document.
That chain is what a model-risk reviewer actually needs, and it is why provenance is mandatory on
every triple from stage 4 onward.

---

## 7. OTEL as a first-class ingestion input

Feeding a sample trace export into ingestion produces a **telemetry profile**: the observed
vocabulary — tool names, workflow names, checkpoint keys and values, outcome enums, state-variable
field names. Ingestion consumes it and emits the `EMITTED_AS_*` binding triples.

It also produces a **drift report**, which is valuable on its own:
- telemetry symbols with no ontology mapping → the implementation does something the policy does not
  describe (`dtmf_4ssn` appears in traces; is it in policy?)
- ontology entities with no telemetry symbol → either untested, or uninstrumented, and those need
  different responses

One caveat to record now: binding to tool-argument field names couples us to the vendor's internal
naming. It works, and we should build it — but it is worth asking whether first-class state
attributes can be added to the spans, which would remove a whole mapping layer.

---

## 8. The two open questions

### 8.1 Is GMS needed in phase 1? — No.
Everything phase 1 requires is symbolic: exact lookup, graph traversal, typed conflict detection,
structural completeness. GMS's value is at the margins where symbols stop — graded plausibility,
fuzzy binding at scale, contradiction beyond typed opposition, multi-hop path consistency, and
**calibrated false-accept rates**, which will eventually be a governance requirement rather than a
nicety.

**Build the `SemanticOracle` interface now; defer the implementation.** Every place semantics are
needed (entity resolution in §5, semantic conflicts in §6b, tier-3 binding in §6.2) calls that
interface. V1 backs it with aliases + embeddings + a reranker/NLI classifier and a calibrated
threshold. GMS, or our own equivalent, slots in later without redesign.

**Trigger for revisiting:** measured. If tier-1/2 binding resolves the large majority of real turns,
and the semantic conflict tier holds acceptable precision on a labelled cohort, GMS stays deferred.
We need that labelled cohort either way — nothing currently produces one, and no semantic verdict
should be trusted before it exists.

### 8.2 How do scenarios and variations work without GMS?
Unchanged in substance from the old generator, just sourced from triples instead of sheets:

- **Scenarios** = route enumeration over `HAS_NEXT_STEP` / `OFFERS_DECISION` / `LEADS_TO`, bounded by
  declared retry limits. The old `core/graph.py` enumeration transfers directly; it never needed
  geometry.
- **Per-scenario ground truth** = the rule assertions in force along the route, compiled
  deterministically — which is what the old code was missing, not what GMS would have added.
- **Variations** = the book's base/enrichment split: presentation factors that are ground-truth
  invariant, enforced by an invariance validator. Pure bookkeeping, no geometry.
- **Probes** = the existing library; its applicability predicates now evaluate over triples
  (`has_capability_of_type`, `has_persistent_memory`, …) instead of intake columns.

Materiality tiering and run counts carry over — with the note that `VARIATIONS_BY_MATERIALITY` is
still an unsigned-off placeholder and blocks any risk-weighted test allocation.

---

## 9. What we borrow, and from where

**Old Scenario Generator — reuse the component, retarget the output**
`core/grounding.py` (quote verification — the strongest asset in that repo) · `ingest/readers.py` ·
the three-pass diagram reading · `ingest/redaction.py` · `core/gaps.py` + open questions ·
`webapp/graphview.py` retry-lane rendering · `core/graph.py` path enumeration · the probe library and
its design rules · LLM tiering / batching / cancellation / metering · the never-destructive repair
discipline (`_accept_if_better`, `_is_thinner`) · "both readings stay visible" for model-vs-declared
disagreement.

**eval-poc — reuse the shape**
Rule-as-node modelling · the rule→assertion compiler pattern (made declarative, not domain-specific
Python) · occurrence-level `TurnGroundTruth` with state before/after · provenance stamping · graph
validation queries.

**The book — reuse the method**
Base/enrichment invariance · the functionality check (recover the answer before admitting an item;
disagreement between symbolic and semantic recovery is a signal about the oracle) · materiality
tiering · trajectory as the unit of observation · weak-link and factor attribution · the fault
taxonomy ordered by detection difficulty · exact numeric memory.

---

## 10. Phasing

| Phase | Deliverable |
|---|---|
| **1a** | Schema: entity types, relation vocabulary with signatures, triple record, validator. Plus the reproducibility harness — built before the extractors it measures. |
| **1b** | Deterministic layer: readers, passages, manifest, redaction, deterministic harvest. |
| **1c** | LLM + vision extraction into the closed schema, with quote verification. |
| **1d** | Correction loops: dedup · conflict · completeness, to fixpoint, with conflict/open-question outputs. |
| **1e** | Freeze, version, reports. **End of phase 1: a triple store we can defend.** |
| **2** | Views: triple editor, workflow view, 2D KG view. |
| **3** | Telemetry profile + reverse binding + turn-level ground truth. |
| **4** | Scenario generation + variations from the triple store. |
| **5** | Evaluator, assertions, attribution. |
| **6** | Semantic oracle / GMS decision, driven by measured gaps. |

---

## 11. Decisions needed before building

1. **Reference use case.** AOP User Identification is what we have real traces for; the
   card-authentication POC is what we have a KG for. They are different agents. Phase 1 should target
   one — recommend AOP, since the trace-binding design depends on real telemetry.
2. **Entity granularity: `State` + `Decision`, or a single `Step`?** The old code separates them;
   eval-poc separates `Step` and `Turn`. Two node types is more expressive and more work to extract
   reliably. Recommend keeping both, with `Decision` optional — a state with one outcome needs no
   decision node.
3. **Store.** Neo4j (eval-poc precedent, good traversal, operational weight) vs. a file-backed triple
   store in git (diffable, reviewable, trivially reproducible, weaker querying). Recommend
   **file-backed as the source of truth, loaded into a graph store for querying** — it makes the
   reproducibility diff a `git diff` and keeps review in the same place as code review.
4. **Who authors rules?** Extracting `Rule` entities from policy changes what the modelling team is
   asked to declare, and whether MRMG authors rules independently. That is a process and independence
   decision, not a schema one.
5. **Human approval tiers.** Which extracted triples can auto-publish and which need sign-off — by
   materiality and by extraction confidence.
6. **Labelled validation cohort.** Required before any semantic tier is trusted. Who builds it, from
   what.
7. **Telemetry instrumentation.** Can we get first-class state/step attributes on spans, or do we
   bind to tool-argument names indefinitely?
