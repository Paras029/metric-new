# *Beyond "Ship and Pray"* — Methodology Digest

> **Source:** Agus Sudjianto & Wing Yan Lau, *Beyond "Ship and Pray": Testing Agentic Systems with
> Geometric Ground Truth*, KnowlytiX, 2026 (KnowlytiX AI Engineering Series).
>
> **Note on form:** This is a working digest — concepts, structures, taxonomies, API surface and
> design arguments extracted for engineering use — not a reproduction of the book text. The book is
> a published, copyrighted work whose own front matter prohibits reproduction. Use the digest for
> design decisions and go to the source for wording.
>
> **Status in this repo:** grounding document. The methodology source for base/enrichment
> separation, designed experiments, multi-level agentic evaluation, failure attribution, resilience,
> and the GMS semantic-oracle concept.

---

## The one-paragraph thesis

Testing a knowledge-intensive LLM or agentic system is a **designed experiment**, not a benchmark. A
benchmark asks how often the system is right; a designed experiment asks under which conditions it
fails and how badly. Two things are required that a benchmark never supplies: (1) **ground truth
correct by construction**, not by annotation, and (2) **a controlled factor space** in which
presentation conditions vary independently of the items themselves. A geometric memory substrate
supplies the first; a catalog of presentation factors supplies the second.

---

## Part I — Foundations

### Ch. 1 — Why average accuracy is not enough

- An aggregate score averages away concentration of failure. A system at 86% overall can fail most of
  the time on one consequential input condition. A model-risk reviewer or regulator asks *under
  which conditions* it fails, not *how often* it is right.
- The organizing device is the **base / enrichment decomposition**:
  - A **base** entry carries the question content *and its ground truth*. The ground truth is
    computed by a substrate primitive — a property of the knowledge graph, not of any model output.
    The base is the experimental unit.
  - An **enrichment factor** is one dimension along which the *presentation* of that question varies
    (asker persona, phrasing, distracting context, adversarial framing…). Each is a treatment
    applied to the base.
- **The invariance requirement** is the load-bearing rule: every factor must be ground-truth
  invariant, recorded as `gt_invariant: true` and enforced by a validator. *A knob that would change
  the answer is a base, not a factor.* This is what makes the method economical — a handful of bases
  expands into a large, factor-balanced, still-automatically-scorable suite.
- Second benefit: bases are domain-agnostic templates bound to whatever graph is supplied, and
  factors describe presentation rather than content — so the same two catalogs carry across domains.

### Ch. 2 — Knowledge graphs and exact memory

- Baseline KG = set of asserted triples `(head, relation, tail)`. Four operations: pattern query,
  traversal (multi-hop), link prediction, entity resolution. Value = exactness + queryable structure.
- Three gaps for *grounding the answer of a system under test*:
  1. **Membership is binary** — the graph cannot say *how wrong* an alternative tail is. A scorer
     needs a degree of correctness.
  2. **No native contradiction or multi-hop consistency measure.**
  3. **Numbers stored as symbolic tails are parse-prone** — a regex over retrieved prose silently
     returns the wrong figure when the sentence is reordered.
- **Exact numeric register (ENM)** repairs gap 3: authoritative numbers live in a separate store,
  keyed by category + identifier, integrity-hashed, returned byte-for-byte. *A figure that matters is
  looked up under its key, never parsed out of retrieved prose.* This is the central data practice.

**What geometry adds to each KG capability**

| Capability | Baseline KG | Geometric memory system |
|---|---|---|
| Membership of (h, r, t) | exact yes/no | graded plausibility (geodesic distance) |
| Missing tail | rule/count-based guess | nearest admissible tail on the manifold |
| Contradiction | not native | tension energy between entities |
| Multi-hop consistency | path exists or not | holonomy defect along the path |
| Numeric value | symbolic tail (parse-prone) | exact register (`lookup_enm`) |
| Confidence | none | calibrated operating point |

- Division of labour: **the graph supplies ground truth correct by construction; the geometry supplies
  a continuous, calibrated oracle** for scoring how far a candidate answer sits from the committed
  fact. Model output is rarely exactly right or obviously absent — it is *near or far*.

### Ch. 3 — GMS primitives

**Two embedding channels**

- **v-space** (semantic): places an entity by what it is about; the relation-conditioned cap that
  `score_triple` reads lives here.
- **u-space** (logical): carries relational/contradictory structure; `tension_energy` is an angle in
  this space.
- A triple is plausible only when its tail lies inside the relation's cap in v *and* is consistent in
  u. That is what lets the store tell "same topic" from "compatible."

**Channel initialization (EmbeddingConfig):** Mode A names a text encoder per channel
(`semantic_model`, `logical_model`) for a warm start; Mode B supplies finished vectors
(`v_vectors_path`, `u_vectors_path`), name-keyed. Mode B takes priority per channel; a warm-started
or loaded channel is frozen by default.

**Supervised fine-tuning:** low-rank adapter, base encoder frozen, drift penalty toward identity.
- v-space → `finetune_embedding`, prototype cosine-softmax objective, **rotation** mode. A rotation
  preserves every pairwise distance; its job is to *align the coordinate frame* to the orthonormal
  (Stiefel) frame the primitives are computed in — it moves the axes, not the distances, so the cap's
  calibration survives.
- u-space → `finetune_contradiction`, contradiction objective over grouped attribute phrasings,
  **full** mode. Full is *required*: tension is an angle, and an orthogonal rotation preserves
  angles, so only stretching can move the separations `tension_energy` measures.

**The primitive set**

| Primitive | Kind | Returns / meaning |
|---|---|---|
| `lookup_enm(category, id)` | exact | byte-exact number from the register |
| `query_triples(head=…, relation=…, tail=…)` | exact | asserted edges matching a pattern |
| `score_triple(h, r, t)` | geometric | geodesic distance; lower = more plausible |
| `link_predict(h, r)` | geometric | ranked plausible tails where nothing is asserted (**prediction, never assertion** — an asserted edge always takes precedence) |
| `tension_energy(a, b)` | geometric | 0 = agree, ≈√2 = unrelated, 2 = contradict |
| `check_holonomy(path, direct)` | geometric | non-negative *defect*: how far composing a relation chain lands from the direct edge; normalized for path length, so chains of different lengths compare |
| `is_path_consistent(path, direct)` | decision | holonomy defect ≤ calibrated `tau_path` |
| `fuzzy_match_entity(surface)` | geometric | surface form → canonical vocabulary (entity resolution) |

**When to reach for holonomy:** whenever a conclusion is reached by *composing* relations rather than
reading one stored edge — transitivity, inheritance, delegation, "A→B→C therefore A→C". Three
recurring cases: multi-hop reasoning certification; delegation/hand-off chains in multi-agent systems
(a broken hand-off shows as a large defect); vetting an inferred edge before committing it. Dividing
line: one stored fact → `query_triples`/`score_triple`; clash between two facts → `tension_energy`;
composed path → holonomy.

**Calibration (non-optional).** A distance is not a decision. Score a labeled cohort drawn from the
store itself (committed facts vs clearly incorrect alternatives) and pick the operating point
maximizing accuracy under a stated false-accept ceiling. **Per relation**, because the distance scale
differs by relation. Persisted with the store.

> **Every decision gate in the system — accept or abstain, grounded or fabricated, relevant or not —
> reads a calibrated operating point.** Only a calibrated threshold has a known false-accept rate; a
> hand-set default has an unknown one and must not be used.

### Ch. 4 — Building the oracle (GEODE)

Three stages: **ingest → self-correction → trained/calibrated store.**

- **Ingest** emits candidate triples (with provenance) plus numeric values for the exact register.
  Three modes: deterministic (rules only, reproducible, exact figures byte-for-byte); hybrid
  (deterministic backbone + LLM at a few decision points); LLM-only (comparison).
- **Geometric ingestion / `GeodeEmbedLoop`:** binding is the other half of correctness — a later query
  arrives in a customer's words ("bounced check charge", "NSF"). A stock encoder has never seen the
  document's vocabulary, and **binding is where retrieval silently fails, because the figure is in the
  store but the query never reaches it.** The loop: train on candidate triples → read back where each
  surface form lands → seed from the document's own alias/name edges → let the geometry *extend* that
  seed (label a surface form with a policy when the trained model places it confidently in that
  policy's neighborhood, even with no explicit alias edge) → fine-tune the encoder on the combined
  supervision → repeat until the label set stops growing. The tuned encoder is carried into the
  production build and reused at query time by the same geometric query parser the agent and grader
  both use.
- **Self-correction loop (`GeodeLoop`):** propose → diagnose (flag candidates that sit implausibly far
  on the manifold or contradict an established fact) → repair or drop → iterate until geometrically
  coherent. Every correction recorded; provenance of accepted facts and fate of rejected ones stay
  auditable.
- **Why it matters:** *an oracle must not inherit the errors of its own extraction.* Attributing a
  failure to the SUT assumes the failure is genuine, which holds only if the store does not encode the
  extractor's mistakes.
- **Precondition for trust:** the store must answer its own generated questions perfectly — a graph
  baseline of full accuracy.

---

## Part II — The experimental material

### Ch. 5 — The base taxonomy (18 categories, 5 families)

Derived *from the graph outward* ("we start from the knowledge graph and ask which kinds of facts it
holds, then ask which questions each kind of fact can support"), not from a collection of prompts
that have tripped systems up. Each category records: required graph capability, the substrate
primitive establishing ground truth, answer type, implementation status.

Capability vocabulary (what makes the taxonomy portable): `enm`, `triples`, `path`, `threshold`,
`ordered_sequence`, `negatives`, `provenance`, `policy`. **A category is admissible for a corpus only
if the store built from that corpus exposes the capability it requires.**

| Category | Family | Answer | Ground-truth primitive | Status |
|---|---|---|---|---|
| `exact_recall` | retrieval | float | `lookup_enm` | implemented |
| `fact_completion` | retrieval | mcq | `query_triples` | partial |
| `plausibility` | retrieval | bool | `score_triple` | specified |
| `absence_detection` | retrieval | bool | `query_triples_empty` | specified |
| `ranking` | comparison | str | `enm_sort` | partial |
| `comparative_discrimination` | comparison | str | `graph_distance` | partial |
| `counting` | comparison | int | `triple_count` | implemented |
| `cross_reference` | comparison | set_str | `set_intersection` | implemented |
| `numeric_computation` | comparison | float | `arithmetic` | specified |
| `cross_table_aggregation` | comparison | float | `aggregate` | specified |
| `multi_hop` | reasoning | tuple | `path_compose` | implemented |
| `reasoning_path_consistency` | reasoning | bool | `check_holonomy` | specified |
| `conditional_rule` | reasoning | bool | `check_threshold` | implemented |
| `procedural_ordering` | reasoning | list | `sequence_check` | specified |
| `contradiction` | consistency | bool | `find_contradictions` | implemented |
| `boundary` | consistency | bool | `check_threshold` | partial |
| `recovery` | behavioral | decision | `expected_abstain` | specified |
| `governance_policy` | behavioral | decision | `policy_rule` | partial |

Notable distinctions worth carrying over:

- **`absence_detection`** is the constructive complement of recall: does the system decline to supply
  a fact the source does not contain?
- **`boundary`** (content-level: *which value* is asked about) is deliberately kept distinct from the
  `edge_case` presentation factor (*how a value is framed*).
- **Behavioral family** (`recovery`, `governance_policy`) differs from the other four: ground truth is
  the *expected behavior* of the system, determined in advance, not a fact in the graph.
- Status is queryable (`implemented` / `partial` / `specified`), so a study reports the coverage it
  actually achieved rather than the coverage the taxonomy permits.

**Three sources of base items** (the enrichment layer treats all three identically):

1. **GMS-mined** — generators mine a trained store; the answer is read from the graph and is provably
   correct.
2. **Labeled seed cases** — hand-labeled cases carrying *per-component* ground truth; used when an
   agent's trajectory, not only its final answer, is under test.
3. **User-supplied pairs** — `(query, answer)` or `(message, label)` supplied directly; the supplied
   answer *is* the ground truth and no store is consulted. This lets a team harden a seed set of real
   queries without building a store at all.

### Ch. 6 — The enrichment design space (40 factors, 10 groups)

Two relations govern how a factor enters an experiment: **invariance** (above) and **relevance**,
recorded as an `applies_to` specification naming the base families and answer types for which the
factor is meaningful. Relevance is applied automatically at resolve time — a set-valued question
drops `numeric_format`; a numeric recall question keeps it.

| Group | Factors |
|---|---|
| query | `query_type`, `clarity`, `length`, `specificity`, `temporal`, `answer_format` |
| persona | `role`, `expertise`, `style` |
| reasoning | `reasoning_cue`, `hop_count`, `reasoning_type` |
| context | `context_scope`, `section_hint`, `distractor_content`, `context_order`, `context_format` |
| entity/value | `entity_aliasing`, `numeric_format`, `unit_variation`, `precision_hint` |
| conversation | `memory`, `history`, `turn_position` |
| adversarial | `instruction_conflict`, `answer_anchoring`, `confidence_pressure` |
| system/agentic | `tool_availability`, `time_pressure`, `iteration_limit` |
| variability | `paraphrase_depth`, `granularity`, `question_format` |
| robustness | `noise`, `context_relevance`, `complexity`, `edge_case`, `emotional_frame`, `format_noise`, `intent_count` |

**Three catalogs, one contract:** `base_catalog.yaml` *defines* the ground truth;
`factor_catalog.yaml` *preserves* it (`gt_invariant: true` + `applies_to`, both validator-enforced);
`profiles.yaml` bundles a named selection of both plus a composition mode.

**Application layer — three levels of customization, in increasing order:**
1. **Select** relevant bases/factors (or a profile) — relevance filtering is automatic.
2. **Override** a factor's level vocabulary via `level_overrides` so a domain reads in its own terms,
   without editing the shared catalog.
3. **Add** a custom factor — a plain YAML entry with the same schema; the one rule is invariance. *If
   varying its levels could change the correct answer, it belongs in `base_catalog.yaml`.*

**Critical boundary — selecting a factor is data; rendering its levels is code.** `compose` writes
choices into `scenario.factor_levels`; turning a level into actual text (making `Ambiguous` read
ambiguously, making a `typo` alias contain a real misspelling) happens in the emit stage's
`materialize_fn`. The default is identity — base query plus factor levels as metadata.

**Methodological point:** ad hoc designs fuse orthogonal dimensions into one factor for economy
(surface corruption + entity aliasing; reasoning cue + adversarial nudge). Fusion reduces columns but
**confounds the dimensions and coarsens attribution** — a failure can no longer be blamed on one
cause. Keep dimensions orthogonal in the catalog and recover compactness through the application
layer.

---

## Part III — Designs and outputs

### Ch. 7 — Experimental design and composition

- The factor space is high-dimensional and of **mixed cardinality** (2 to several dozen levels).
  Full factorial is out; classical fractional-factorial constructions don't exist for these irregular
  cardinality patterns.
- Approach: generate **space-filling designs in the continuous unit hypercube**, discretize to factor
  levels, minimize the **φp** criterion. φp controls the *fill distance*, which bounds the
  noncentrality parameter of the likelihood-ratio test for factor effects — so minimizing φp
  **maximizes statistical power at fixed budget**. Gradient optimizer, Sobol-scrambled init, annealed
  refinement, cardinality-weighted distance so many-level factors aren't starved by binary ones.
- **Two arrangements:**
  - **Crossed** — design covers presentation factors only; each base item paired with every design
    row. Exhaustive per item; cost grows with item count.
  - **Embedded** — base is promoted to a factor and varied jointly. Fixed-size suite, more economical,
    and (because the base is a factor) failures can be attributed to the base item itself.
- **Marginal balance caveat:** embedding a high-cardinality base under a modest budget lets joint
  space-filling leave individual base items under-represented or absent. Default resolution is
  conservative: treat an embedded base as a **balanced blocking factor** — equal proportions, with
  presentation factors space-filled *within* that allocation. Pure joint design reserved for budgets
  that can cover every base level.

### Ch. 8 — Generating training data / from design to evidence

One composed design, two consumers:

1. **Supervised corpus.** Classifier emitter produces label-preserving `(message, label)` records —
   because enrichment varies the surface while the label is invariant by construction, a corpus is
   synthesized *without re-labeling*. Draft emitter produces grounded QA pairs validated against an
   explicit **golden contract** (cite the governing source; contain byte-exact figures; avoid
   prohibited commitments). Kept and dropped pairs returned separately, so the corpus is grounded by
   construction and rejections remain auditable.
2. **Evaluation.** Run scenarios through the SUT; score at three levels (outcome, trajectory
   structure, process health); regress binary correctness on factor levels.

**The functionality check** — the part most worth stealing. Before a generated question is admitted,
the harness *recovers* the answer from the store and confirms it equals the stated ground truth. Two
recovery routes:

- **Symbolic** — re-apply the generator's answer function to the store's recorded facts and check
  equality. Authoritative statement of *what the answer is*.
- **Geometric** — confirm the trained manifold also supports the answer's fact triple: the recovered
  tail must be more plausible than the relation's other candidate tails and fall within the relation's
  *calibrated admissibility*. Many-to-many aware — a tail is judged against tails the head does *not*
  assert, never its own siblings.

> A question survives only when both agree. **The disagreement is itself informative:** the symbolic
> check asks whether the answer is what the store records; the geometric check asks whether the
> trained geometry has actually learned it. A conflict is a signal about the oracle, not a tie to be
> broken. The recorded answer is still the truth — the store is simply unreliable there, and admitting
> the question would make it an unfair test of a system that itself consults the geometry.

Items are labeled by how they were admitted: *doubly grounded*, or *symbolic-only* where the answer is
an aggregation (count, ordering) with no single fact triple to recover.

Generators also emit **balanced cohorts by construction** — e.g. the path-consistency generator pairs
each real triangle with a corrupted twin 50/50 and leaves the discrimination threshold to the
calibrated judge rather than baking in a cutoff.

**User-supplied path:** when a team brings their own pairs, the oracle and category generators are
skipped entirely; only the DoE enrichment applies. Store-mined and user-supplied paths differ only in
where bases originate; they meet at the same enrichment and the same consumers.

---

## Part IV — Evaluating agentic systems

### Ch. 9 — What to test in an agentic system

- An agent runs a perceive–decide–act loop. In regulated deployments it is usually a **fixed
  workflow** — the tool sequence decided in advance — which makes states enumerable and failure modes
  countable. Two structures wrap it: a stack of **gates** screening every proposed action (well-formed
  call, policy-compliant, admissible next step) and an **escalation** path to a human. Every step is
  written to an append-only audit log.
- **Why answer testing is insufficient:** an agent can reach the right final decision by the wrong
  route (escalate a benign case for a spurious reason); a tool can fail silently and the agent proceed
  on a corrupted result; a run can terminate without ever producing a clean answer (a *process*
  failure, distinct from a wrong answer).

> The unit of observation is the **trajectory**: the ordered record of proposed actions, gate
> decisions and tool observations, terminating in an answer, an escalation or a failure. This is the
> same unit whether the agent follows a fixed workflow or chooses each action dynamically — and that
> common unit is what lets one methodology test both.

- **The SUT as an interface, not an implementation.** Minimal contract: a callable mapping query +
  context → answer (enough to score outcome). A structured result (`SUTResult`) unlocks the rest:
  per-component predicted values, ordered trajectory, terminal status, escalation trigger. An adapter
  wraps the deployed agent and maps its trajectory using the agent's own accessors — *it reports what
  the agent did and introduces no new judgment of its own.*

**Stages, in order (parts before the whole, then behavior, then faults):**

| Stage / check | Mechanism |
|---|---|
| Test design | space-filling factor design (Chs. 5–7) |
| Ground truth | generated from the oracle, not annotated (Chs. 2–4) |
| Component correctness | per-tool ground truth; `weak_link` |
| Retrieval recall | graph-truth recall/precision with parse/bind/retrieve localization; abstention as coverage |
| Groundedness | calibrated `score_triple` distance bands on a stated claim |
| Provenance | each claim cites a source sentence whose span contains the value |
| Stance verification | asserted stance vs stored stance (supported / contradicted) |
| Answer claim extraction | geometric query parser over the answer (store-bound triples) |
| Recovery | the `recovery` base category (expected abstention) |
| Governance (gates) | gate decisions vs policy/workflow graph |
| Outcome correctness | `evaluate.run` against labeled ground truth |
| Failure attribution | logistic factor attribution + `weak_link` |
| Trajectory structure | per-step admissibility + escalation path (fixed workflow: prescribed order) |
| Process health | step/tool-call/failure counts; clean termination |
| Resilience | tool fault injection (Ch. 11) |
| Robustness of phrasing | variability + robustness factor groups |
| Conversational behavior | conversation factor group |

- **Fixed vs dynamic workflows.** Component, system and resilience testing are identical because every
  stage scores the trajectory. The one difference is the trajectory-structure check: a fixed workflow
  is scored for **adherence** (did it follow the prescribed order); a dynamic agent has no prescribed
  order and is scored on **order-independent invariants** — every action an *admissible* next step (the
  plausibility gate applied at each turn rather than once), no loop or repeated action without
  progress, termination within budget, reaching a valid goal or escalating cleanly. *Adherence is the
  special case of admissibility where the admissible set has exactly one member.* ReAct maps directly:
  the action is what admissibility tests, the observation is what component scoring tests, and the
  reasoning step is tested only as an artifact to be grounded, never as evidence on its own credit.

**Scoring a retrieval component** — the obvious rule is wrong. A retrieval tool doesn't emit a label;
it binds a question to the graph and returns the fact that answers it. The faithful measure is
**graph-truth retrieval**: a test case is a question paired with the value the graph holds; grading
runs the agent's own path (parse → bind → retrieve) and counts a hit when the retrieved *value*
matches. Every miss localizes to **parse** (didn't resolve into store vocabulary), **bind** (resolved
but attached to the wrong head), or **retrieve** (right head, wrong relation — an adjacent-relation
confusion).

Two principles keep it faithful: (1) the agent and evaluator share **one** parse and one ranking — the
evaluator never re-parses with a different tool or substitutes a stricter candidate set; (2) an
**abstention is coverage, not error** — a query the store cannot ground is answered correctly by
silence, so it lowers coverage without lowering recall.

Two tempting shortcuts that corrupt the score: grading against a downstream **routing label** (which
may name a different policy than the one retrieved, manufacturing mismatches on cases the retriever
got right), and grading against a **post-retrieval admissible subset** (after a later filter dropped a
plausible candidate, making recall look low exactly when retrieval succeeded). Both compare against a
proxy for the answer rather than the answer the graph holds.

### Ch. 10 — Logistic attribution of failure

- The response is Bernoulli; ANOVA is the wrong tool (it degenerates into a linear probability model,
  can predict outside [0,1], and misstates variance). Use **logistic regression**, binomial family,
  logit link, factor levels as indicators against a reference level.
- **Analysis of deviance** (likelihood-ratio test, the proper analog of the F-test): fit null vs full
  (adding the factor's L−1 indicators), refer the deviance difference to χ² on L−1 df. Report
  McFadden's pseudo-R² as the variance-explained analog of η².
- Per level: empirical correctness rate with a **Wilson score interval** (well-behaved at extreme
  rates) and an **odds ratio** exp(βj) against the reference.
- **Multiple comparisons matter and change conclusions.** Benjamini–Hochberg FDR correction; only
  corrected significance is grounds for action; merely suggestive factors are recorded as items to
  watch.
- **The artifact a model-risk reviewer actually consumes** is not a fraction correct — it is "a
  particular phrasing, at a particular level, fails at a particular rate within a stated interval."
  Specific and remediable.
- **Joint model** reports pseudo-R², AIC, BIC, ROC-AUC and a Hosmer–Lemeshow calibration p-value — and
  serves as the empirical instrument showing a space-filling design beats a quasi-random one at fixed
  budget (higher pseudo-R², lower information criteria from the same number of runs).
- **Interactions** (additive vs product-term models, tested by default only among individually
  significant factors) and **per-category analysis** (same attribution within each question category,
  localizing a weakness that strikes multi-hop but spares exact recall).
- **Weak-link / component attribution** — orthogonal to factor attribution. Assign each failed run to
  the **first tool, in execution order, whose output was wrong**; tabulate the distribution of blame. A
  tool is scored only on runs where it executed and a correct answer is defined. *Factor attribution
  identifies which input drives failure; the component decomposition identifies which part of the
  system is responsible.* Read together.
- **Small-sample discipline:** with few failures a logistic fit is unstable and odds ratios can diverge
  at levels with no failures — the robust report is then the **empirical failure rate** per level.

### Ch. 11 — Resilience under tool faults

- In production a tool failure is a certainty, not an edge case. A governed agent must **fail loud**:
  escalate rather than pass a corrupted result into a customer-facing answer. This is the failure mode
  a regulated deployment most needs to exclude, *because a bad tool result that propagates silently is
  invisible to any test that scores only the final answer* — the answer can look perfectly reasonable
  while resting on a fact the tool never returned.
- Probe: install a `ToolGateway` on the executor, apply one `FaultProfile` to one tool at a time, run
  the suite, measure **detection rate** = fraction of runs where the agent escalated rather than
  silently continuing. Correct agent: detection 1.0, silent-failure count 0, on every tool.
- Detection counts only when the agent both **reached** the faulted tool and **failed loud**; a run
  that escalated earlier doesn't count for that tool.

**Fault taxonomy ordered by detection difficulty:**
1. **Hard error / timeout** — easy: nothing usable comes back.
2. **Stale data** — harder: well-formed but out of date; nothing about its shape betrays it.
3. **Plausible-but-wrong structured result** — hardest: right type and shape, wrong content. Passes
   any syntactic check; catchable only downstream by a verifier comparing against the substrate
   (exact-register check on a number, geometric check on a claim).

The canonical instance is a **stance reversal**: a drafted reply naming the right entity and relation
but inverting the meaning — "optional" where policy says required, "permitted" where forbidden. The
**value-polarity verifier** scores the asserted stance against the stored stance and returns
supported / contradicted / uncertain. (Reported result: 3 of 4 reversals flagged contradicted; the
miss scored *uncertain* — a deferral to review, not a false pass.)

> The gateway establishes that an outright failure is detected; the verifiers establish that a
> plausible-but-wrong result is. Together they close the gap the probe alone would leave open.

---

## Part V — Capstone (Ch. 12): the whole method on one governed agent

**System under test:** a governed banking complaint agent — fixed five-step workflow
(`classify_complaint` → `extract_facts` → `search_policy` → `flag_regulatory` → `draft_response`)
under a gate stack (Syntax → Policy → GMS plausibility), with a hash-chained audit log. Driven
unchanged, through an adapter — *the one piece of application glue*, which is what keeps the framework
package domain-neutral.

**Three escalation diverters:** gate refusal on input (PII, prompt injection, prohibited advice —
caught at the *first* tool call, never reaching the classifier); high-severity regulatory flag
(severity read from the graph by multi-hop traversal, not hard-coded); unsafe draft caught by the
output verifier.

**The validation plan** maps each Ch. 9 property to a mechanism and a section — component, governance,
groundedness, stance, overall, failure attribution, trajectory, process health, resilience.

**Test construction:** 20 labeled seed cases entering via `SeedCaseSource` (carrying per-component
ground truth plus an adversarial marker) × 3 presentation factors (`clarity`, `entity_aliasing`,
`reasoning_cue`) → embedded balanced design, Sobol+refine, 120 scenarios, seed case exactly balanced
(six each). **One balanced suite, scored many ways.** Materialization is deterministic templated
surgery by default; opt-in LLM rephrasing costs reproducibility, so cited campaigns read from a fixed
materialized suite.

**Ground truth generation:** answer key read from the same GEODE-built store the agent runs on —
governing policy and accept-set graph-connected; regulation severity a graph traversal; authoritative
fee an exact-memory value; legal workflow transitions the `has_enables` edges. The one authored input
is the seed cases' classification labels.

> **The precondition:** because the answer key is read from the graph and not authored, a failure is
> chargeable to the agent rather than to a noisy key. That is exactly the condition Ch. 1 set for
> calling this a designed experiment rather than a benchmark.

**Selected results worth remembering as engineering lessons:**

- **Gates:** Policy gate perfect on both paths (5/5 adversarial refused at the first call, 15/15 benign
  admitted — both directions of error zero). Plausibility gate admitted 5/5 legal transitions, denied
  14/20 illegal; every *gross* violation (multi-step skip, reversal) caught. The six misses were all
  **near-neighbor** transitions (self-repeats, single-step skips) scoring just under threshold. The
  fixed-workflow agent never proposes them — *but it is exactly the boundary a test must surface,
  because an LLM planner swapped in for the fixed workflow could reach it.* Closing it is a
  recalibration question, not a code change.
- **Retrieval:** operator-native retriever recall 0.85 / precision 0.85, parse 1.00 / bind 1.00; dense
  top-5 baseline on the *same tuned encoder* reached 0.65 / 0.31 — so the gap is the retrieval
  *mechanism* (triple mediation), not the embedding. All three misses at the **retrieve** stage: right
  policy, adjacent field. *That is why localizing the miss matters — the work left is relation
  disambiguation on the bound head, not retrieval.*
- **Draft groundedness:** committed fee scored geodesic 0.056 (grounded band); fabricated $50 scored
  ≈1.55 (fabrication band). A draft stating no checkable claim is scored **n/a** rather than forced
  into a verdict. Provenance consistency 1.00 (33/33 claims cite a span containing the value).
  Deterministic and replayable — *the same draft yields the same number a year later, which an LLM
  judge cannot promise.*
- **Attribution:** with few failures (9/92 classifier, 1/18 flagger) the report is the **empirical rate
  per level**, not odds ratios; rates were flat and no factor survived correction (clarity nearest at
  p_adj = 0.96). This *reversed* the earlier finding on the previous agent, where a downplaying cue was
  the dominant driver — the retrained classifier and operator-native retriever no longer break on those
  factors.
- **Overall decision 0.675** (81/120) — but the breakdown is the point: 28 runs never reach a graded
  component (PII/injection intercepted at the gate, graded separately, entering the joint criterion as
  zero). Of runs that do reach a component: 23/32 inquiry, 41/42 complaint, 17/18 regulation-implicating.
  Setting gate-intercepted safety inputs aside, 81 of 92 decided correctly. **A single rate conflates
  the reasons a run fails.**
- **Operational:** workflow adherence 1.000; audit log verifies across the campaign — *so any failure
  surfaced elsewhere is behavioral, not an integrity failure of the record.*
- **Resilience:** detection rate 1.0 on every tool, silent-failure count 0.

---

## Appendix C — The space-filling design mathematics (essentials)

- **φp criterion:** `φp(X) = (Σ_{k<l} d_kl^(−p))^(1/p)`. Large p makes the sum dominated by the
  smallest distances; as p→∞ minimizing φp converges to maximizing the minimum inter-point distance
  (classical maximin).
- **Continuous relaxation:** drop the Latin-hypercube constraint, treat the design matrix as a free
  continuous variable, optimize over unconstrained Z and recover X through a sigmoid. Bonus: a point
  pushed toward the boundary lands in the sigmoid's flat tail where its gradient ≈ 0 — a soft
  repulsion from the walls, which is wanted because a point pinned to the wall fills less space.
- **Log-space evaluation + analytic gradient:** naive evaluation overflows at large p; the loss and
  gradient are computed in log space and share the same `−p·log d` matrix, so peak memory is one n×n
  matrix plus the design. Autodiff would tape the whole pairwise computation and inflate memory past
  the O(n²) floor.
- **p-annealing:** geometric ladder of exponents; early small-p stages see a smooth landscape and are
  easy to descend; later stages sharpen focus toward closest pairs from a good configuration.
- **Sobol+Refine init:** scrambled Sobol sequence (low discrepancy), clamped away from the saturating
  tails, then polished by gradient descent — global uniformity from the sequence, local repulsion from
  the refinement.
- **Mixed cardinality:** cardinality-weighted distance `w_j = |L_j| / mean(|L|)` scales each axis by how
  finely it can be resolved, so a 12-level factor isn't treated as equal to a binary one.
- **Why it means power:** fill distance bounds the noncentrality parameter of the LR test → smaller
  fill distance = larger noncentrality = greater power to detect a true effect at fixed runs.

---

## What this book contributes to the Metric re-architecture

**Adopt (methodology, no GMS dependency):**

1. Base / enrichment separation with enforced `gt_invariant` + `applies_to` relevance filtering.
2. Three base-item sources — store-mined, labeled seed cases with per-component truth, user-supplied
   pairs — all meeting the same enrichment layer.
3. The functionality check: recover the answer before a generated item is admitted; treat
   symbolic/geometric disagreement as a signal about the oracle.
4. Trajectory as the unit of observation; admissibility as the general form of workflow adherence.
5. The stage ordering: components → system → operational → resilience, scored independently.
6. Dual attribution: factor (logistic + FDR, or empirical rates when failures are few) and weak-link
   (first erring component).
7. Fault taxonomy ordered by detection difficulty; fail-loud detection rate; the value-polarity /
   stance verifier for plausible-but-wrong results.
8. "Selecting a factor is data; rendering its levels is code."
9. Grading a retrieval component against **graph truth** with parse/bind/retrieve localization, and
   abstention counted as coverage rather than error.
10. Space-filling design when statistical attribution becomes a requirement — with the balanced
    blocking default for high-cardinality embedded bases.

**Treat as optional / replaceable (the GMS layer):** two-channel embeddings, geodesic plausibility,
tension energy, holonomy, calibrated per-relation operating points, GEODE's geometric self-correction.
These are semantic-oracle *capabilities* to sit behind an interface — valuable where symbolic
traversal stops (fuzzy binding, graded claims, contradiction, multi-hop consistency, known
false-accept rates), not architectural prerequisites.

**Carry over regardless of substrate:** exact numeric memory (numbers as typed keyed data, never
re-parsed from prose), calibration-before-decision discipline, and provenance/versioning on every
assertion.
