# Design Plan 06 — The Ingestion Pipeline, v1

**Status:** the design to build. Supersedes the pipeline sections of plans 02 and 04 where they
differ; plan 05's assessment of GEODE stands.

**What "robust enough" means here.** v1 is not the pipeline that catches everything. It is the
pipeline whose **failures are visible**. Every mechanism below earns its place by making a specific
silent failure loud; anything that only improves a number we cannot yet measure is deferred, with the
trigger for adding it written down.

---

## 1. At a glance

```
  documents                        ┌─ schema.yaml  (human-owned, versioned)
  pdf · docx · xlsx · md · png     │
        │                          ▼
   1 ── corpus ──────────► passages ──────┐
        manifest, readers,                │
        furniture, redaction              │
                                          ▼
   2 ── harvest ─────────► candidates (deterministic: numerics, modals, tables)
                                          │
   3 ── batch ───────────► batches + frozen glossary  (pass A)
                                          │
   4 ── extract ─────────► candidates (llm, schema-constrained, quote-bound)  (pass B)
                                          │
   5 ── admit ───────────► admitted │ quarantined(reason)
                                          │
   6 ── reconcile ───────► dedup → conflicts → integrity
                                          │
   7 ── freeze ──────────► graph · quarantine · questions · reports · manifest
```

Seven stages. Stages 1–3 and 5–7 are deterministic. Stage 4 is the only place a model decides
anything, and everything it produces must survive stage 5.

---

## 2. Data model

Five types carry the whole pipeline.

```python
@dataclass(frozen=True)
class Passage:
    id: str                      # sha1(doc_id | location | normalised_text)[:12]
    doc_id: str
    location: str                # "p3" | "sheet:Tools!r4" | "§3.D"
    kind: Literal["prose", "table", "list", "heading", "image"]
    heading_path: tuple[str, ...]
    text: str

@dataclass(frozen=True)
class Span:
    passage_id: str
    start: int                   # char offset into Passage.text
    end: int
    quote: str                   # verbatim, as it appears in the source

@dataclass(frozen=True)
class Candidate:
    head: str                    # surface form, not yet an entity
    head_type: str
    relation: str
    tail: str                    # surface form or literal
    tail_type: str
    span: Span
    method: Literal["deterministic", "llm", "vision"]

@dataclass(frozen=True)
class Triple:
    head: str                    # entity id — sha1(type | canonical_name)[:10]
    relation: str
    tail: str                    # entity id, or a typed literal
    spans: tuple[Span, ...]      # ≥1; more after a merge
    method: frozenset[str]
    materiality: Literal["high", "normal"]
    status: Literal["admitted", "conflicted"]

@dataclass(frozen=True)
class Rejection:
    candidate: Candidate
    criterion: str               # which admission check failed
    detail: str
```

`Rejection` is a first-class type rather than a log line. That single decision is most of what makes
v1 debuggable.

---

## 3. The schema file

One human-owned YAML per use case, extending a core file. This is the difference between our design
and GEODE's, and it is cheap to build.

```yaml
version: 1
extends: core

entity_types:
  structural: [Capability, State, Decision, Outcome, Action, Tool, Turn,
               Rule, Condition, StateVariable, Value, Persona]
  domain: [Customer, Card]          # use-case specific, freely extended

relations:
  - name: HAS_NEXT_STEP
    domain: [State]
    range: [State]
    cardinality: many
    materiality: high

  - name: RULE_FORBIDS
    domain: [Rule]
    range: [Action, Outcome, State]
    cardinality: many
    polarity: negative              # drives the polarity check, §5.4
    materiality: high

  - name: HAS_CANONICAL_TEXT
    domain: [Turn]
    range: [literal]
    cardinality: one
    materiality: normal
```

Three fields do real work. `domain`/`range` make a malformed triple rejectable structurally rather
than arguable. `polarity` is what lets us catch a requirement extracted as a prohibition.
`materiality` decides how hard the triple has to work to get admitted (§5.5).

Nothing is ever required to be *present*. A use case with no tools, or no conversational turns, is
valid.

---

## 4. Stages 1–3: getting to batches deterministically

### Stage 1 — Corpus → passages

Readers for PDF, DOCX, XLSX/CSV, MD/TXT and images. **Port these from the old repo rather than
writing them** — `ingest/readers.py` already handles the formats, and its behaviour on a scanned PDF
(refuse with a reason rather than read as empty) is correct.

Three things happen here that matter later:

- **Furniture stripping.** Lines repeating across pages ("Card Authentication Voice Bot • 1") are
  removed before passaging, or they pollute quotes and break span verification.
- **Tables keep their header.** A table row becomes a passage with the header prepended. This is the
  single highest-value parse decision: without it, "maximum of 3" binds to whatever prose happened to
  be adjacent.
- **Redaction** runs before anything leaves the process.

Passage ids are content hashes, so the same document always yields the same ids regardless of
processing order.

### Stage 2 — Deterministic harvest

Regex and table rules over passages, producing candidates with `method="deterministic"`:

- numerics with units and their subject (`maximum of 3`, `within 60 days`)
- modal sentences (`must`, `must not`, `may`, `shall`) → `Rule` candidates with polarity from the modal
- `(key, value)` and `(condition, action)` table rows
- explicit tool/outcome tables — the policy's §5 is exactly this shape

**Why first:** every candidate harvested here is one the model is never asked for. On a document like
the working policy this covers most of the facts that matter, and covers them without a cross-check
being needed — which is precisely the class GEODE's critic admits it cannot correct (plan 05 §4).

### Stage 3 — Batching, and the glossary

Batches are token-budgeted and structure-aware: boundaries only at headings, paragraph breaks, list
items and table rows; one unit of overlap each side; a table never split from its header. Each batch
carries a context header — document title, heading path, and the glossary.

**Pass A** reads every batch independently for entity mentions only and freezes the result. **Pass B**
(stage 4) extracts triples with the complete frozen glossary.

This two-pass split is the one piece of non-obvious machinery in v1, and it is not optional: the
single-pass alternative accumulates the glossary as batches process, which makes batch *N* depend on
batches 1…*N*−1. Reordering the corpus would then change the graph, and an early error would
propagate forward. Two passes cost roughly 30% more calls and remove both problems.

---

## 5. Stage 4–5: extraction and admission

### 5.1 The extraction call

One call per batch. Structured output, with `relation` as an enum of the active schema:

```json
{
  "non_normative": false,
  "triples": [
    {"head": "authenticate_customer", "head_type": "Tool",
     "relation": "RETURNS", "tail": "AUTHENTICATED", "tail_type": "Outcome",
     "quote": "authenticate_customer returns AUTHENTICATED"}
  ]
}
```

`non_normative` is how a batch says *there was nothing here* as distinct from *I found nothing*. A
batch that returns neither triples nor `non_normative: true` is re-read once, then reported. This is
the coverage audit, and it is the only defence against under-extraction — a fact that was never
emitted is otherwise invisible.

### 5.2 Admission

Candidates are not in the graph until they pass, in order:

| # | Criterion | Check |
|---|---|---|
| 1 | schema valid | relation exists; `head_type`/`tail_type` satisfy domain/range; cardinality respected |
| 2 | quote located | the quote is findable in the cited passage — **port `grounding.py` from the old repo**; tolerant of PDF mangling, intolerant of rewording |
| 3 | polarity consistent | negation markers in the quote vs the relation's declared polarity |
| 4 | value present | for a value-bearing relation, the cited span actually contains the value |
| 5 | materiality bar | high-materiality triples need a deterministic origin **or** a second witness |

Anything failing lands in quarantine with the criterion and the candidate. Criterion 4 is the book's
provenance-consistency check applied at admission rather than as a later report, which is cheaper and
catches more.

### 5.3 What v1 does *not* do here

No entailment check. Criterion 2 verifies the quote exists; it does not verify the quote supports the
claim. That gap is real (plan 04 §LH4) and v1 covers it differently: **high-materiality triples
whose only support is an LLM extraction go to the review queue**, not into the graph. An entailment
model gets added when we have a labelled cohort to calibrate it on — adding it before that just moves
the unvalidated judgement.

---

## 6. Stage 6: reconcile

Three passes, in this order, iterating until nothing changes (bounded at 5).

**Dedup** on canonical form, not text. Constraint-bearing triples reduce to
`(subject, constraint_kind, operator, value, scope)` before comparison, so the working policy's three
phrasings of the attempt limit — "maximum of 3", "up to 3 total", "must not make a fourth attempt" —
collide on one key and survive as one triple carrying three spans. Deontic triples reduce to
`(scope, modality, action)` the same way.

**Conflicts**, deterministic and typed:

- one `Outcome` with two different `LEADS_TO` tails
- a `State` both terminal and carrying `HAS_NEXT_STEP`
- two values for one canonical key
- `RULE_REQUIRES` and `RULE_FORBIDS` over the same `(scope, action)`
- a `Condition` on an undeclared variable

Conflicts are never auto-resolved. Either declared document precedence applies (version + effective
date, from the manifest) or it goes to the queue.

**Integrity**, conditional — nothing is required to exist, but what exists must be coherent: every
outcome leads somewhere or its state is terminal; every state reachable; every decision with ≥2
outcomes; every rule attached to a scope; every condition resolvable; no orphans. Failures become
open questions.

Ordering is deliberate — dedup first, or duplicates masquerade as conflicts. The loop only ever adds
resolutions within a run; reversals are a human action between runs, which is what stops it
oscillating.

---

## 7. Stage 7: three outputs, not one

| Output | Contents |
|---|---|
| **graph** | admitted triples, canonically sorted, with spans and method |
| **quarantine** | every rejected candidate, its failing criterion, its quote |
| **questions** | integrity gaps, unresolved conflicts, high-materiality LLM-only triples awaiting review |

Plus a build manifest: corpus hashes, schema version, prompt hash, model id and params, code version.
Same tuple must mean the same graph.

**The review loop in v1 is a file, not a UI.** `questions.yaml` is edited in place — answer, approve,
reject — and re-ingestion consumes it. Decisions are keyed by the hash of the text they were made
about, so an unchanged passage keeps its decision and a changed one re-queues. That keying is cheap
now and is the difference between a tool you run once and a tool you run every quarter.

---

## 8. What v1 defers, and what triggers adding it

| Deferred | Why it is safe to defer | Trigger to add |
|---|---|---|
| Entailment check | high-materiality LLM-only triples go to review instead | a labelled cohort exists to calibrate on |
| GEODE geometric critic | needs torch + GPU; unproven on our corpus | the spike shows it catches something dedup and integrity miss |
| Full derivation-graph provenance | spans + build identity answer "what supports this" | we need blast-radius analysis for a policy change |
| Path / model-checking conflicts | the graph must be trustworthy first | integrity checks are clean and conflicts still slip through |
| n-vote consensus | costs k× for an unmeasured gain | the reproducibility harness shows real drift |
| Full fault-injection suite | v1 ships ~6 injectors for the highest-value detectors | a detector is suspected of never firing |
| Three-pass diagram reading | the policy's prose (§3) gives the same backbone | a corpus arrives where the diagram is the only source |
| Telemetry binding | that is phase 3, not ingestion | — |

Six injectors in v1, chosen because each targets a failure that is otherwise silent: polarity flip,
rule split across a batch boundary, restated fact, contradictory value in a second document, detached
table header, fabricated quote.

---

## 9. GEODE in v1

Take the parts that are deterministic and drop in without a GPU:

- **`normalize_graph`** — tier-1 deterministic normalisation of entity surface forms, with the
  singleton-never-renamed rule that protects against over-merge. Runs *inside* our declared schema,
  on entity names only; relation rewrites are rejected at the boundary.
- **`ProvenanceLedger` / `is_consistent`** — evaluate against our `Span` model; adopt if it fits
  without contorting ours.
- **`resolve_duplicates`** — evaluate against our canonical-form dedup; whichever is better on the
  fixture wins.

Everything geometric — `CompositionCritic`, `AnchorChecker`, `GeodeLoop` — stays behind a seam and
out of the v1 build path until the spike says otherwise. Pin the commit; a GEODE bump is a
build-identity change.

---

## 10. Done means

On the golden corpus (`grounding/07` plus its flowchart):

1. Two builds produce byte-identical admitted triples.
2. Precision and recall reported per relation family against an annotation written by someone who did
   not write the prompts.
3. The three phrasings of the attempt limit appear as **one** triple with three spans.
4. The prohibition stated in §3B and §4 appears as **one** rule with two spans.
5. Every rejected candidate is in quarantine with a reason.
6. `transfer_to_ccp → FAILED` appears with **no destination and an open question** — no invented state.
7. All six injectors trip their detector.
8. Editing `questions.yaml` and re-running preserves every decision whose passage is unchanged.

Criterion 6 is the one to watch. It is the cheapest thing to accidentally "fix", and passing it is the
clearest evidence the pipeline reports reality rather than flattering itself.

---

## 11. Effort

Rough bands, one engineer, assuming readers are ported rather than written:

| | |
|---|---|
| scaffold, schema, types, store | ~1 week |
| corpus layer (ported) + harvest | ~1 week |
| batching, glossary, extraction, admission | ~1.5 weeks |
| reconcile, reports, questions loop | ~1 week |
| harness, fixture, annotation, injectors | ~1 week |
| **total** | **~5–6 weeks to criterion-complete** |

The annotation in criterion 2 is the only item that needs someone other than the engineer, and it is
worth booking early — it is on the critical path for the accuracy gate and it cannot be done by
whoever wrote the prompts.
