# Key Findings — Scenario Generator as-built vs. the ontology-driven target

> Analysis of `paras029/metric` @ `c4f6d8e` (24.7k LOC Python) against the strategy notes
> (`01`), the reverse-GT brief (`02`), the real OTEL trace envelope (`03`), the eval-poc
> executable-oracle pattern (`04`) and the *Beyond "Ship and Pray"* methodology (`05`).
>
> File references are `path:line` at that commit.

---

## 1. What the Scenario Generator actually is today

Verified against the code, not the README. It is a **test-space compiler plus an LLM authoring and
review pipeline**, ending at "issue a workbook and measure how much of it the team's own testing
already covers."

**The data model** (`core/models.py:51-109`) is an agent-structure model:

| Entity | Fields | Line |
|---|---|---|
| `Capability` | `id, name, type` | `models.py:52` |
| `Decision` | `id, name, trigger_capability, inputs, variants, input_source, max_attempts, outcome_condition, out_of_scope` | `models.py:59` |
| `State` | `id, reached_via, description, next_decisions, is_terminal, outcome_type` | `models.py:78` |
| `Persona` | `id, name, applies_to, is_default` | `models.py:88` |
| `Tool` | `name, capability_id, state_changing` | `models.py:96` |

Closed vocabularies: `CATEGORIES` (Happy path / Retry / Fallback / Escalation / Termination),
`MATERIALITY` (Low→Critical), `CAPABILITY_TYPES` (Lookup / Transactional / Gating / Advisory /
PII-handling), `INPUT_SOURCES` (User / Tool / Memory-Session / Memory-CrossSession / System-Context /
Document), `ORIGINS` (graph / variant-gap / probe / llm-proposed).

**The pipeline** (`pipeline.py`) runs: `ingest_documents` → `draft_intake_workbook` /
`revise_intake_workbook` → `build_graph` → `build_probes_stage` → `refine` (LLM writer) →
`assess_materiality` → `review` → `build_pack` → `map_conversation_coverage` → `annotate_coverage`.

**Enumeration** (`core/graph.py`) is a DFS over states with `(decision, variant)` edges, bounded by
each decision's own `max_attempts` (`graph.py:94-96`) with `MAX_DEPTH = 12` / `MAX_PATHS = 1000` as
backstops (`graph.py:25-26`), plus a second BFS pass giving a focused path to every declared
`(decision, variant)` the DFS missed (`graph.py:155-172`).

**Outputs**: a *data template* issued to the modeling team — `Instructions`, `Scenarios`,
`Turn_Plan`, `Variation_Log`, `Variation_Summary`, containing no expected outcomes
(`io/workbooks.py:204-248`) — and a *scenario space metadata* workbook kept internally, 26 columns
including per-turn `TurnMeta` (`io/workbooks.py:32-39, 66-67`).

### What is genuinely good and must not be lost

1. **Determinism where it matters.** Category comes from the declared `Outcome Type` of the terminal
   state, never a model call (`generation.py:22-40`). Probe applicability is predicate-based over
   intake facts (`probes.py:52-62`). Persona binding is deterministic. The comment discipline
   throughout states *why* a thing is deterministic.
2. **The extraction-grounding guard** (`core/grounding.py`) — a claim whose verbatim span cannot be
   located in the source is discarded, not flagged, because "a fabricated citation is worse than no
   citation." Tolerant of PDF mangling, intolerant of rewording. This is the eval-poc's missing
   provenance layer, already built.
3. **Never-destructive repair.** `_accept_if_better` (`pipeline.py:372-396`) writes a repaired intake
   to a scratch path, re-audits it, and keeps the original if the repair is worse. `_is_thinner`
   (`pipeline.py:464`) rejects a "revision" that collapsed the graph. Both are exactly the discipline
   an ontology compiler will need.
4. **Both readings stay visible.** Materiality has `materiality` / `review_materiality` /
   `materiality_override` with an explicit precedence property (`models.py:209-211`); category has
   `category` / `review_category` (`models.py:179`). A model's revision never overwrites the
   deterministic value — it lands beside it and a person rules.
5. **Origin discipline + legacy translation.** `canonical_origin` (`models.py:36-39`) translates an
   older workbook's spelling on the way in, so scenarios don't silently drop out of downstream
   filters. `FUNCTIONAL_ORIGINS` separates routes-through-the-graph from probes for coverage
   denominators (`workbooks.py:287`, `pipeline.py:551-559`).
6. **Coverage as annotation, never a filter** (`pipeline.py:575-605`) — and deliberately never
   reaching the issued pack, because telling the team which scenarios are already answered tells them
   which to concentrate on.
7. **The probe library's design rules** (`probe_library.yaml:1-38`): one property per probe, domain
   neutral (enforced by a banned-vocabulary test), transcript-assessable, objective applicability.
   27 probes. This is a well-governed asset.

---

## 2. The five structural gaps

### Gap 1 — The "ground truth" is generated, stored, and never used to grade anything

`TurnMeta` is documented as "Per-step ground truth from the graph" (`models.py:137`). Tracing every
consumer of `expected_variant` / `expected_tool`:

| Consumer | What it does | Line |
|---|---|---|
| `build_turn_meta` | creates it | `generation.py:76-77` |
| `_write_turn_sheet` | writes it to a workbook | `workbooks.py:93` |
| `read_scenarios` | reads it back | `workbooks.py:127` |
| `read_scenarios` | rebuilds a `Step` path from it | `workbooks.py:170` |
| `fallback_name` | renders a display string | `generation.py:91` |
| `ScenarioWriter` | hands it to the LLM as context for prose | `writer.py:232` |

**It is never compared against anything an agent did.** There is no evaluator, no assertion, no
verdict, no pass/fail anywhere in the package. The closest thing is `map_conversation_coverage`,
which reads the returned data template *as conversations* (`ingest/conversations.py:195-252`) and
asks an LLM "which scenario does this transcript look like?" (`llm/conversation_mapping.py`),
producing `Mapping(scenario_id, confidence, intent, ending, reason)`.

That answers **"did they test this scenario?"** It does not answer **"did the agent behave
correctly?"** The loop closes on coverage, not on correctness. This is the single biggest gap
between the code and every one of the notes.

### Gap 2 — Branch conditions are prose that nothing parses

`Decision.outcome_condition` (`models.py:67`) exists on every decision. Its only consumers:

- `llm/context.py:76` — rendered into a prompt string
- `webapp/graphview.py:191` — displayed as "Selected when" in the UI
- `ingest/drafting.py`, `ingest/diagram_structure.py` — written during extraction

**Nothing ever evaluates it.** Contrast the eval-poc, whose `PathResolver.condition_holds` actually
parses `NEXT.when` against a `RuntimeContext` with two regexes
(`_RETURNS_RE`, `_ATTEMPT_CMP_RE`) — crude, but executable.

The Metric graph therefore has *no runtime state at all*. A path is a sequence of `(decision,
variant)` labels; there is no `RuntimeContext`, no counter, no state variable, no precondition, no
postcondition. `max_attempts` is enforced as a DFS loop bound (`graph.py:94-96`), not as a
checkable assertion about the agent. Compare the notes' requirement: *"Transition conditions are
structured predicates rather than only natural-language 'when' strings"* (01 §5.2).

### Gap 3 — No policy/deontic layer, therefore no assertions and no provenance on expectations

The intake has six sheets — `L1 Use Case`, `Personas`, `L2 Capabilities`, `L3 Decisions`,
`L4 States`, `Tools` (`core/intake.py:21-22`, template at `intake.py:406-422`). There is **no rule
sheet**. There is nowhere to say "the agent must not attempt a fourth authentication", "success may
only be claimed after an AUTHENTICATED result", "no servicing after transfer."

The eval-poc has exactly this and it is the more mature half of the design: 13 `Rule` nodes as
first-class graph entities with `code / statement / rule_type / subject / predicate / object /
polarity`, attached via `GOVERNED_BY` to steps, turns and tools, and compiled by a registry of
functions into typed `GroundTruthAssertion` objects carrying `category`, `predicate`, `severity`,
`source_rule_id`, `source_step_id`, `source_turn_id`, `expected_value`. An unregistered rule code
produces a WARNING-severity "uncompiled" assertion rather than vanishing.

Consequences in Metric today:

- Expectations have **no provenance**. Nothing links a scenario expectation back to a policy
  sentence. The `grounding.py` evidence machinery exists but stops at the intake draft — it never
  reaches the scenario or its expectations.
- There is **no severity**. Every expectation is equally weighted; nothing distinguishes a blocker
  from a nice-to-have.
- **Prohibitions are unrepresentable.** The graph can only say what happens, never what must not.
  `out_of_scope` (`models.py:68`) is the closest thing and it means "don't test this," not "the agent
  must not do this."

### Gap 4 — Scenario-first only; no trace entry point

`read_scenarios` and `read_space_metadata` (`workbooks.py:113, 269`) are the only ways into the
scenario model, and both read a workbook that this tool wrote. There is no path from an observed
agent trace to an expectation. The brief's proposed `resolve_ground_truth_from_observed_turn`
(02 §18) has no counterpart in the code.

The nearest thing, `ConversationMapper`, runs the wrong direction and with the wrong authority: it
asks a model to classify a transcript into a pre-existing scenario, rather than resolving what policy
required at the observed state. Its output carries `confidence: "high"` for anything the team
*stated* on the returned template (`conversation_mapping.py:152-154`) — a self-declared label, not a
derived fact.

### Gap 5 — No enrichment layer, no DOE, no invariance concept

The book's base/enrichment split and the eval-poc's `factor_catalog.yaml` +
`InvarianceValidator` have no analogue here. Metric has:

- `Persona` — bound deterministically by category (`generation.py:43-48`), one per scenario, not a
  varied factor.
- Probes — adversarial *content*, carrying no decision path (`probes.py:125-145`). These are
  additional bases, not GT-invariant presentation variants.
- `VARIATIONS_BY_MATERIALITY = {"Low": 1, "Medium": 3, "High": 5, "Critical": 10}`
  (`models.py:47`), explicitly marked **"PLACEHOLDER — pending MRMG sign-off"**.

The variation count asks the team to run the same scenario N times. It does **not** vary presentation
under controlled factors, and nothing records what varied between run 1 and run 5 — so nothing can
attribute a failure to a condition. That is precisely the "aggregate hides where it fails" problem
the book opens with.

---

## 3. The OTEL trace envelope changes the reverse-GT plan

`03-otel-trace-sample-galileo.json` is the most consequential new input, because both the brief
(02 §13, §26 A) and the strategy notes (01 §9, §14) flag "what metadata does the real agent emit?"
as *the* determinant of reverse-GT complexity. We now have the answer, and it is **Level B with a
deterministic escape hatch** — better than feared, worse than the brief's Level A.

### What the envelope gives us

- **Structure:** 1 session per conversation, 1 trace per turn, spans ordered `llm(user_message)` then
  `tool`/`workflow`. Stable ids: `gen_ai.conversation.id`, `galileo_turn_id`, `call_sid`,
  `decagon.trace_id`, plus `correlation_id` / `flow_run_id` per tool call.
- **Tool calls in full:** name, `event_type` (`audit_api` vs `audit_tool`), input JSON, output JSON,
  status, latency. Deterministic tool grading is available today.
- **Workflow span:** `name: "User Identification"`, `input: "Selected AOP User Identification"` —
  a capability-level anchor.

### What it does not give us

**There is no `step_id`, no `turn_id`, no state-variable attribute, no attempt counter, no terminal
status, no escalation flag.** The brief's Level A ("metadata-rich trace → direct KG lookup") does not
exist as such.

### The finding that rescues it

**Runtime state is recoverable, but it is hiding inside tool payloads rather than in span
attributes.** Three carriers:

1. **`set_metadata` calls are explicit state writes.**
   `{"policy_input": ["check_fullssn_or_cm15_called", "true"]}`,
   `{"policy_input": ["checkpoint", "check14Key"]}`,
   `{"policy_input": ["checkpoint_14key", "4SSN"]}`.
   These are literally `(state_variable, value)` assignments — a checkpoint machine emitting its own
   transitions.
2. **Tool *inputs* carry a state snapshot.** `check_fullssn_or_cm15` is called with
   `no_user_pref_counter`, `user_response`, `check_fullssn_or_cm15_response`; `check_14key` is called
   with `_14key_input_error`, `_14key_searching_counter`, `_14Key_unsure`, `checkpoint_14key`,
   `_4ssn_api_response`… The counters the eval-poc tracks in `RuntimeContext` are **already on the
   wire**, as tool arguments.
3. **Tool *outputs* are the branch outcomes.** `{"match": "NO_USER_RESPONSE"}`,
   `{"match": "NO_PREFERENCE_SHARED"}`, `{"match": "UNKNOWN"}`,
   `{"status": "PROFILE_NO_MATCH"}` — a closed outcome vocabulary, exactly the `Outcome` nodes an
   ontology needs.

**Implication:** a `StateBinder` can be ~deterministic for this agent if the ontology's state
variables are keyed to the *actual* variable names in `set_metadata` / tool-arg payloads. This is a
mapping-table problem, not a semantic-embedding problem. The GMS/fuzzy-binding question can be
deferred exactly as 01 §11.4 recommends — but it means **the ontology must model the agent's real
state vocabulary, not an idealized one.** That is an ingestion requirement nobody has scoped yet.

### Three further observations from the trace

- **The real agent is not the POC.** The trace is AOP *User Identification* — ANI check → full SSN or
  CM15 preference → 14-key → 4SSN, with DTMF fallbacks and counters. Richer than the card-auth POC,
  and the ontology work has to be sized against this, not against the 6-step fictional procedure.
- **ASR corruption is a first-class failure mode, in production.** `"Five Centimeters fifteen,
  please"` is "5 CM 15 please"; `"My god number"` is probably "my card number"; `"Bye. I think
  something went wrong. Green."` is garbled. The evaluator **must** separate "the agent handled the
  transcript wrongly" from "the transcript was wrong." The book's insistence on keeping intended
  input, materialized audio, ASR transcript and agent behavior as separate artifacts (05, blueprint
  §9.2) is not optional here — it is the dominant real-world condition.
- **Traces end badly and must still be gradable.** Turns 4 and 5 have an LLM span and no tool spans;
  the final assistant content is empty. A trace-first evaluator has to treat "no tool call happened"
  and "the turn produced nothing" as *observations to assert against*, not as parse failures.

---

## 4. Two discrepancies worth resolving before design work

1. **The notes describe capability-scoped enumeration; this commit does not have it.**
   01 §2.1 says: *"Capabilities therefore define entry and exit states, and the graph is enumerated in
   bounded spans."* `core/graph.py` at `c4f6d8e` enumerates globally from `start_states`, bounded only
   by per-decision `max_attempts` and the `MAX_DEPTH`/`MAX_PATHS` backstops. `Capability` is used for
   tool linkage (`generation.py:51-63`) and probe predicates, **not** for scoping enumeration. Either
   the notes were written against `scene_generator_latest.zip` (a newer tree than this repo), or the
   capability-span design is aspirational. **Which tree is authoritative needs settling** — it changes
   whether capability spans are "preserve this" or "build this."

2. **`VARIATIONS_BY_MATERIALITY` is still a placeholder pending sign-off** (`models.py:46-47`), and it
   is the only lever connecting risk to test volume. Any DOE/enrichment work inherits this open
   decision; the notes' "risk-weighted coverage using materiality" (01 §8.3) rests on numbers nobody
   has approved.

---

## 5. What the re-architecture actually is

Restating the target in terms of *this* codebase, the change is **not** a rewrite. It is three
insertions and one inversion.

### Insert 1 — a policy/deontic layer into the intake

Add rule representation alongside the existing six sheets: a rule id, a typed kind
(sequence / constraint / grounding / scope / transition / terminal / tool-contract), structured
subject-predicate-object, severity, scope (state / turn / tool / capability / journey), and — using
machinery that already exists in `grounding.py` — an evidence span and policy version. The eval-poc's
13 rules are the working prototype of the vocabulary; `grounding.py` is the provenance guard it never
had.

### Insert 2 — structured state and transition predicates

Give `Decision.outcome_condition` a machine-readable sibling. Minimum viable: observed outcome value,
counter comparison, destination state — i.e. what `PathResolver.condition_holds` parses, but declared
rather than regex-scraped from prose. Add a typed state-variable declaration so
`RuntimeContext` has something to be an instance *of*, and key those variable names to what the
traces actually emit (§3).

### Insert 3 — the EvaluationContract and an assertion compiler

`TurnMeta` becomes the seed of a richer per-occurrence record (the eval-poc's `TurnGroundTruth`
already shows the shape: occurrence id, sequence, expected tool call, expected result, expected next
state, state before/after, linked assertion ids). A rule→assertion registry compiles the policy layer
into typed assertions. The compiler must be **generic + declarative**, not the eval-poc's
domain-specific Python registry — that is its named limitation (02 §23.1) and the notes' named risk
(01 §17).

### The inversion — `resolve_for_scenario` and `resolve_for_trace` behind one resolver

This is the structural change. Today the only entry point reads a workbook this tool wrote. Add a
trace entry point that binds an observed OTEL turn to an ontology state and resolves the same
contract type. Both call the same rule/state engine, which is what stops the synthetic benchmark
drifting from production evaluation.

Then, and only then, the evaluator: deterministic graders for tool identity/arguments/outcome,
counters, transitions, ordering, terminal state; a constrained semantic judge for free-form response
meaning *against a resolved contract*; assertion-level explanations.

### Sequencing (my recommendation)

The notes' Phase 0–3 ordering is right, with one amendment. Do **Phase 0 + the trace-envelope
mapping together** — the state-variable inventory from real traces is an input to the ontology
design, not a later integration step. Everything else follows: executable ontology → unified
resolver → deterministic evaluator → reconnect the Scenario Generator → enrichment/DOE → semantic
oracle. Defer GMS entirely until a measured gap justifies it.

---

## 6. Open questions this analysis surfaced

1. **Which tree is authoritative** — this repo, or `scene_generator_latest.zip` with capability spans?
2. **Does the challenge-pack model survive?** Trace-first evaluation of production conversations and
   "issue a blank workbook, get it back filled in" are different products with different governance.
   Both can share the ontology, but the notes never say whether the pack remains the deliverable.
3. **Who owns the rule layer?** Adding deontic rules to the intake changes what a modeling team is
   asked to declare, and whether MRMG authors rules independently of them. That is a process decision
   with independence implications, not just a schema change.
4. **Can we get the agent instrumented, or do we bind to payloads forever?** Reading state out of tool
   arguments works but couples the evaluator to Decagon's internal variable naming. Worth asking for
   first-class state attributes on the span before building a large mapping layer.
5. **What is the reference use case?** The notes say "select one narrow use case." AOP User
   Identification is the one we have real traces for; the card-auth POC is the one we have a KG for.
   They are not the same agent.
6. **What does a labeled validation cohort look like here,** and who adjudicates? Required before any
   semantic judge is trusted (01 §14, §13.3) and nothing currently produces one.
