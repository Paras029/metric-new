# Strategy Brief: KG-Grounded Testing of a Stateful Voice Agent

> **Source:** Internal handover document (`WHOLE_STRATEGY_BRIEF_FOR_AI.md`), provided as context.
> **Status in this repo:** grounding document — the reverse-ground-truth thesis and the POC/book
> comparison this re-architecture builds on.

---

## Purpose of this document

This document is a self-contained context pack. It describes two related but importantly different
implementations:

1. **The methodology described in _Beyond "Ship and Pray": Testing Agentic Systems with Geometric
   Ground Truth_** (the book / KnowlytiX methodology).
2. **The Card Authentication Voice Bot POC**, which borrows selected principles from the book but
   intentionally uses a much simpler procedural knowledge graph and does not implement GMS.

The immediate strategic question is how to evolve the POC from a **scenario-first evaluator**
(scenario + precomputed ground truth → agent → evaluation) into an **agent-trace-first evaluator**
where an actual observed turn is used to query the KG, reconstruct the ground truth that applies at
that moment, and then evaluate the agent response/action.

The goal is not to reproduce the book literally. The goal is to understand exactly what the book is
doing, exactly what the POC is doing, why each layer exists, what value it provides, and which parts
are actually necessary for the intended reverse-ground-truth evaluation.

---

## 1. Executive picture

At the highest level, both approaches are trying to solve the same problem:

> How can we test an AI agent against ground truth that is trustworthy, reproducible, auditable,
> and independent of the agent being tested?

The key idea is to make the **knowledge source authoritative**, rather than using an LLM or an
analyst's manually written answer key as the ultimate truth.

The major difference is how far the methodology goes:

### Book / KnowlytiX direction

The book builds a full testing methodology around a **knowledge graph + GMS (Geometric Memory
System)**. The graph stores asserted facts; GMS adds learned geometry, graded plausibility,
contradiction, path consistency, calibrated thresholds, exact numeric memory, and other verification
primitives. The resulting store acts as an oracle for generated questions and for validating real
agent trajectories.

### POC direction

The POC uses a much smaller **procedural Neo4j KG**. It stores a voicebot's workflow as structured
`Step`, `Turn`, `Tool`, `Outcome`, and `Rule` nodes and relationships. A Python `GroundTruthOracle`
reads that graph, resolves a scenario path, expands the graph turns into occurrence-level
expectations, compiles rules into atomic assertions, and produces a replayable ground-truth
artifact.

The POC therefore proves a narrower but highly relevant proposition:

> A procedural KG can act as an executable specification of agent behavior and can generate ground
> truth for scenario-based testing. The same graph may also be usable as an online ground-truth
> resolver for real agent traces, potentially without GMS for the initial use case.

---

## 2. What the book is trying to accomplish

### 2.1 The fundamental problem

An aggregate accuracy number hides where a system fails. A designed experiment instead asks under
what conditions the system fails and how badly.

That requires two things:

- **Ground truth that is correct by construction**, rather than an uncertain human annotation.
- **A controlled factor space** in which presentation conditions can be varied independently of the
  underlying truth.

The basic decomposition is therefore:

```
BASE QUESTION / CASE + GROUND TRUTH
        plus
GROUND-TRUTH-INVARIANT ENRICHMENT FACTORS
```

The factor changes presentation, not truth. The same policy question can be phrased clearly,
ambiguously, formally, casually, or with additional context, while the underlying correct answer
stays fixed. This separation makes the test suite expandable without requiring relabeling every
variant.

### 2.2 Why the knowledge graph matters

The book treats knowledge as a graph of asserted triples `(head, relation, tail)`, for example
`(overdraft, has_fee_amount, 35)` or `(dispute, has_window_days, 60)`.

A traditional graph supports exact pattern queries, graph traversal / multi-hop reasoning, entity
resolution, and exact membership checks. What makes it valuable is exactness and structure: an
answer is a triple the source asserts, and the relations make the structure of the domain explicit
and queryable.

However, an ordinary graph has limitations for evaluating generated outputs:

- membership is binary (true/false), not graded;
- contradiction is not naturally represented as a numerical measure;
- multi-hop consistency is not natively measured;
- numeric values stored as symbolic tails can be error-prone if reparsed from prose.

### 2.3 What GMS adds

GMS sits on top of the graph and turns symbolic knowledge into a geometric verification substrate.
It distinguishes two embedding channels:

- **v-space**: semantic similarity and relation-conditioned plausibility;
- **u-space**: logical / contradiction structure.

Key GMS capabilities:

1. `query_triples` — exact asserted graph reads.
2. `lookup_enm` — exact numeric memory lookup.
3. `score_triple` — graded plausibility of a candidate triple.
4. `link_predict` — plausible but non-asserted completion.
5. `tension_energy` — contradiction / compatibility measure.
6. `check_holonomy` — multi-hop path consistency.
7. `is_path_consistent` — calibrated decision from holonomy.
8. `fuzzy_match_entity` — surface-form to canonical-entity binding.
9. Calibrated operating points for turning geometric distance into grounded / not-grounded
   decisions.

The conceptual role of GMS is important:

> **The graph says what is asserted. GMS gives a measurable way to judge how close a candidate claim
> is to what the graph represents.**

This is why the book can use the substrate itself as the ground-truth mechanism.

### 2.4 Building the oracle in the book

The book's oracle construction process is GEODE:

```
source document -> candidate facts -> self-correction -> trained / calibrated store
```

The self-correction step matters because a knowledge store built directly from noisy extraction
would merely encode extractor mistakes. GEODE uses the store's own verification machinery to
diagnose implausible or contradictory candidates, repair/drop them, and then train/calibrate the
surviving store. The resulting store is intended to be a trustworthy oracle, not simply a search
index.

### 2.5 Test generation in the book

The methodology moves from oracle → questions → controlled scenarios. It defines a taxonomy of base
question categories derived from the capabilities of the knowledge graph: 18 categories across five
families (retrieval and recall; comparison, ranking and aggregation; reasoning and composition;
consistency and integrity; behavioral and operational).

Ground truth is tied to a graph primitive. Examples: exact recall → exact numeric memory; counting →
triple count; multi-hop → path composition; conditional rule → threshold comparison; governance
policy → policy graph / rule.

The test suite can use three sources for base items:

1. items mined from the store itself;
2. hand-labeled seed cases carrying per-component truth;
3. analyst-supplied `(query, answer)` or `(message, label)` pairs.

This is useful because the framework does not require every test to be store-mined.

### 2.6 Enrichment and experiment design

The book distinguishes **what the test asks** from **how the test is presented**. It defines 40
enrichment factors covering query form, persona, reasoning cue, context, entity/value variation,
conversation context, adversarial instructions, system/tool conditions, paraphrase/variability, and
robustness. Every factor must be `gt_invariant: true`.

For experiment composition, the book uses designed experiments rather than random sampling. It
proposes crossed or embedded designs and a Sobol + refine / space-filling approach to cover the
factor space efficiently. The purpose is statistical attribution: failures can be analyzed as a
function of the controlled factors using logistic regression and related analyses.

### 2.7 Agentic evaluation in the book

A critical conceptual shift is that an agent should not be evaluated solely by its final answer.
The unit of observation is the **trajectory**: proposed actions, tool calls, tool
observations/results, state transitions, terminal status, escalation path, final answer.

The book distinguishes several layers of evaluation:

- **Component level** — test individual tools/gates against their own ground truth.
- **System / outcome level** — ask whether the final decision is correct.
- **Operational level** — ask whether the agent followed the required workflow and terminated
  properly.
- **Resilience level** — inject failures and test whether the agent fails loud rather than silently
  propagating bad tool results.
- **Attribution** — use factor-level analysis to understand which input conditions drive failures,
  and a weak-link decomposition to identify the first failing component in the trajectory.

### 2.8 Grounding a real agent response in the book

One especially relevant idea is the book's answer-driven claim grounding:

```
agent answer -> extract checkable claim/triple -> bind to graph vocabulary -> compare against graph ground truth
```

For exact facts, graph membership / exact memory may be sufficient. For semantic plausibility or
near-miss cases, GMS's geometric machinery supplies graded judgments. This is the closest book
concept to the reverse-GT idea proposed for the POC.

---

## 3. What the current POC is doing

### 3.1 Intent and scope

The POC is intentionally much smaller than the book's implementation. It models one fictional Card
Authentication Voice Bot whose job is to:

1. open the interaction;
2. authenticate the customer;
3. permit at most three authentication attempts;
4. communicate success or failure;
5. transfer the call to CCP;
6. do no additional servicing.

Evaluation-critical behaviors: opening before authentication; correct authentication attempts;
maximum 3 attempts; correct success/failure messaging; transfer after success or max retry; no
additional servicing. This is deliberately minimal and does not model card replacement, transaction
review, delivery selection, etc.

### 3.2 The procedural KG schema

The Neo4j graph models the operating procedure as structured entities.

**Voicebot** — root entity `Voicebot(card_authentication)` with version and source document.

**Steps** — `opening`, `authentication`, `retry`, `success`, `max_retry`, `transfer`.

**Turns** — tied to steps, with actor (`BOT`, `CUSTOMER`), turn type, canonical text,
required/generated flags, embedding text. Examples: `opening_bot`, `authentication_prompt`,
`authentication_customer`, `retry_bot`, `success_bot`, `max_retry_bot`.

**Tool** — `authenticate_customer`, expected output `AUTHENTICATED | FAILED`.

**Outcomes** — `AUTHENTICATED`, `FAILED`, `CLEAR`, `UNCLEAR`.

**Rules** — first-class KG entities: `OPENING_BEFORE_AUTH`, `AUTHENTICATION_REQUIRED`,
`MAX_THREE_ATTEMPTS`, `ATTEMPT_COUNTER_PERSISTS`, `UNCLEAR_IS_FAILURE`,
`SUCCESS_REQUIRES_AUTHENTICATED`, `FAILURE_MESSAGE_BEFORE_RETRY`,
`MAX_RETRY_MESSAGE_BEFORE_TRANSFER`, `NO_ADDITIONAL_SERVICING`, `TRANSFER_AFTER_SUCCESS`,
`TRANSFER_AFTER_MAX_RETRY`, `END_ON_TRANSFER`.

This is why the KG is more than a simple flowchart: it also captures the normative rules governing
behavior.

---

## 4. How the current graph represents the procedure

The main control-flow edges are `NEXT` relationships:

```
opening -> authentication

From authentication:
  AUTHENTICATED                  -> success
  FAILED + attempt_count < 3     -> retry
  FAILED + attempt_count = 3     -> max_retry

retry     -> authentication
success   -> transfer
max_retry -> transfer
```

The graph therefore captures both **workflow shape** and **branching conditions**. The retry loop is
particularly important because the graph's Turn IDs can repeat in the scenario expansion while the
concrete turn occurrence must remain distinct.

---

## 5. The Python oracle in the POC

Core classes: `GraphReader`, `PathResolver`, `RuleCompiler`, `GroundTruthExtractor`.

### 5.1 GraphReader

A thin typed read layer over Neo4j: query the graph, convert Neo4j results into plain dictionaries,
hide database-driver details from the rest of the code. The rest of the framework thinks in domain
objects and dictionaries rather than raw Neo4j records.

### 5.2 PathResolver

Takes a scenario's runtime authentication outcomes and walks the `NEXT` relationships. It evaluates
conditions such as `authenticate_customer returns AUTHENTICATED` and
`authenticate_customer returns FAILED AND attempt_count < 3`. This turns a graph containing possible
branches into one concrete legal journey for a specific scenario.

> **The important architectural idea:** The graph defines the legal transitions. The scenario
> supplies the runtime conditions.

### 5.3 RuleCompiler

Rules are not left as prose only. `RuleCompiler` maps known KG rule codes to concrete
`GroundTruthAssertion` objects — authentication calls ≤ 3; attempt counter starts at 1 and increments
by one without reset; success state can only follow `AUTHENTICATED`; retry failure message precedes
another authentication attempt; transfer follows success/max-retry; transfer is terminal.

This provides a machine-checkable bridge from policy rules to evaluation. Unknown rules do not
silently vanish: the current fallback creates an `uncompiled` warning assertion.

### 5.4 GroundTruthExtractor

Combines resolved path, expected turns, expected tool calls/results, rule-derived assertions,
state before/after each turn, and provenance/version information into a versioned `GroundTruth`
object.

The key object is `TurnGroundTruth`, storing: occurrence ID; sequence; step ID; turn ID; actor;
expected text; expected tool call; expected tool result; expected next step; state before; state
after; applicable assertion IDs. This is already very close to what is needed for the reverse lookup
problem.

---

## 6. What Notebook 15 shows

Notebook 15 (`15_scenario_inspector.ipynb`) is the clearest view of the current scenario
representation. It loads a scenario artifact and converts it to a pandas dataframe with one row per
turn occurrence, with columns including: `seq`, `actor`, `step`, `turn_id`, `utterance`, `attempt`,
`input_label`, `expected_bot_response`, `expected_tool`, `expected_tool_attempt`,
`expected_tool_result`, `expected_next_step`, `attempts_before`, `attempts_after`,
`auth_state_after`, `n_assertions`, `rules_checked`, `evaluator_checks`.

This dataframe exposes the exact data contract already available to the evaluator. The notebook
notes that `turn_id` can repeat (e.g. `authentication_prompt`) while `seq` is unique — meaning the
real unit is the **turn occurrence**, not merely the static Turn node ID.

The evaluation interpretation is: BOT rows → expected bot response; CUSTOMER rows → expected tool,
tool attempt, tool result; all rows → expected next step and state/attempt movement; rules → linked
assertions checked locally or over the whole journey.

The notebook also demonstrates that base and enriched scenarios share the same ground truth while
changing only customer presentation — the concrete implementation of the base/enrichment principle
borrowed from the book.

---

## 7. Current scenario-first architecture

```
Operating Procedure
      |
      v
Procedural KG
      |
      v
Path enumeration / scenario generation
      |
      v
Scenario conditions
      |
      v
GroundTruthExtractor
      |
      v
Scenario artifact
  + expected trajectory
  + rules / assertions
      |
      v
Simulator / Agent
      |
      v
Observed trajectory
      |
      v
Evaluator
```

The simulator is deliberately not allowed to use the expected bot turns as its script. It receives
customer inputs and simulates the agent according to the policy, while the environment can control
the authentication outcome. This keeps the intended test boundary intact: the agent generates
behavior; ground truth comes from the scenario/KG side.

---

## 8. The simulator: what it contributes and what it does not

The simulator is conceptually separate from the KG oracle. Its job is to approximate the behavior of
an agent operating under the same operating procedure.

It keeps state such as current step, authentication attempt count, last authentication result,
authenticated flag, transferred flag, conversation history. It produces structured outputs
containing bot response, tool call, tool outcome, current step, next step, attempt count,
authentication state, transfer state.

The current implementation uses an LLM for behavior generation, structured via a Pydantic output
schema. For test purposes, the authentication environment supplies the scripted scenario tool
outcome — so the simulator tests the agent's response to a known environment outcome rather than
asking an LLM to decide whether credentials are actually valid.

This is useful for controlled experiments, but it also creates the central strategic question: **how
do we evaluate a real agent trace when no scenario was pre-generated?**

---

## 9. The current evaluator and its simplified interface

The current intended evaluation interface is a scenario dataframe. A simulated run adds
`simulator_bot_output` and `simulator_tool_call`.

The immediate POC metrics are:

1. `response_correctness`
2. `tool_correctness`

The response judge can use an LLM because natural-language responses can be paraphrases of the
canonical text. The tool check can be deterministic because tool identity can be matched exactly.
The policy Markdown can be passed into the LLM judge so semantic correctness is evaluated against
the authoritative operating procedure rather than only text similarity.

SafeChain is the approved LLM wrapper in this environment; the intended pattern is LangChain-style
initialization around SafeChain, with environment/config loaded first. The immediate evaluation
layer is intentionally small and is not meant to reproduce the entire book's scoring stack.

---

## 10. The proposed reverse-ground-truth strategy

This is the main strategic evolution being discussed. Instead of starting from a scenario with a
known answer key, start from an **actual agent trace**.

```
Actual customer utterance
+ agent response
+ metadata (step, turn, state, tool call/result, attempt, etc.)
          |
          v
Identify where this observation sits in the KG
          |
          v
Traverse the relevant local graph structure
          |
          v
Construct a turn-level GT contract
          |
          v
Evaluate the actual response/action against that contract
```

This does **not** mean the agent response becomes the truth. The intended interpretation is:

> The observed trace provides runtime context. The KG provides the normative truth.

This preserves the independence of the evaluator.

---

## 11. Why the existing KG may already be sufficient

For the current authentication POC, the KG already contains most of the information needed to
answer: What step am I in? What turn is applicable? What tool is valid here? What tool outcomes are
possible? What state transition should follow this outcome? What rules govern this step/turn/tool?
What behavior is required or allowed? Is the step terminal?

If the real agent trace already gives reliable metadata such as `step_id`, `turn_id`,
`attempt_number`, tool call, tool result, customer utterance, agent response — then most GT
resolution becomes ordinary graph lookup/traversal, not semantic embedding.

For example:

```
observed:
  step        = authentication
  turn        = authentication_customer
  attempt     = 2
  tool_result = FAILED
```

The graph can determine:

```
expected tool     = authenticate_customer
expected branch   = retry
expected next step = retry
applicable rules  = max-three-attempts, retry-message, etc.
```

No GMS is inherently necessary for those operations.

---

## 12. Proposed `KGStateResolver`

Input: an observed turn.

```python
ObservedTurn(
    step_id="authentication",
    turn_id="authentication_customer",
    attempt_number=2,
    customer_utterance="...",
    agent_response="...",
    tool_call="authenticate_customer",
    tool_result="FAILED",
)
```

Output: a turn contract.

```python
ResolvedTurnContract(
    step_id="authentication",
    turn_id="authentication_customer",
    expected_tool="authenticate_customer",
    valid_tool_outcomes=["AUTHENTICATED", "FAILED"],
    expected_next_step="retry",
    expected_behavior="inform customer that authentication failed and request another attempt",
    applicable_rules=[
        "MAX_THREE_ATTEMPTS",
        "ATTEMPT_COUNTER_PERSISTS",
        "FAILURE_MESSAGE_BEFORE_RETRY",
    ],
)
```

The actual response is then evaluated against that contract. This is conceptually the same knowledge
already produced by `GroundTruthExtractor`; the difference is that the contract is generated **on
demand for an observed turn**, rather than pre-generated for a whole scenario.

---

## 13. Two possible levels of reverse resolution

### Level A: metadata-rich agent trace

If production/test telemetry provides reliable state and turn metadata, use it directly:
`step_id + turn_id + attempt + tool result` becomes a direct KG lookup + transition resolution. This
is the easiest and most deterministic path.

### Level B: raw-text-only trace

If the evaluator receives only customer utterance, agent response, and maybe tool call, it has to
infer which KG turn/state applies. For example, `"I wasn't able to verify those details, please try
again"` needs to bind to `retry_bot`; a customer message needs to bind to `authentication_customer`.

Potential solutions: an LLM resolver; embedding similarity; document/entity-aware retrieval;
eventually GMS/fuzzy entity matching if the system grows toward the book's architecture.

> The important point is that this semantic-binding problem is different from the actual
> **ground-truth evaluation** problem.

---

## 14. Where GMS is and is not needed

**Clearly deterministic with the current KG:** step lookup; turn lookup; valid tool lookup;
tool/result validation; branch resolution; next-step resolution; retry count checks; transition
ordering; rule applicability; terminality.

**Semantically fuzzy but manageable with an LLM judge:** whether a free-form bot message communicates
the required meaning; whether a paraphrase still satisfies the policy; whether a generated response
claims the right outcome.

**Capabilities where GMS would become useful:** graded plausibility of a claim; fuzzy entity binding
at scale; contradiction detection; path-consistency / holonomy; calibrated distance-based
acceptance; near-miss semantic scoring rather than binary comparison.

> The strategic view should not be "we need GMS because the book uses GMS." It should be: use the
> simplest substrate that solves the present evaluation requirement; add geometric machinery only
> when the required evaluation semantics exceed what deterministic KG traversal + LLM semantic
> judgment can provide.

---

## 15. How the reverse approach maps to the book

The proposed reverse approach is not outside the book's conceptual framework. The book treats the
trajectory as the unit of observation for agentic testing, and describes using graph-based ground
truth for governance and using the graph/GMS substrate to judge generated claims.

```
Book:
agent trajectory -> claim/tool/trajectory observation -> graph/GMS oracle -> evaluation

Simplified implementation:
agent turn -> identify KG state -> graph traversal/rules -> turn contract -> deterministic + LLM evaluation
```

The difference is that the POC uses the **procedural graph directly**, while the book's more advanced
implementation uses GMS for continuous/semantic verification.

---

## 16. What the reverse design buys us

> **We do not need to know the complete expected scenario in advance.**

A real or replayed agent trace can be evaluated after the fact. This matters operationally because
real production conversations do not arrive pre-packaged as scenario artifacts.

The evaluator could take customer input, agent output, state metadata and tool metadata, and
reconstruct the relevant normative contract from the policy KG. This moves the system closer to
**policy-grounded observability and continuous evaluation** rather than only synthetic benchmark
execution.

It also means the same KG could serve two roles:

1. **offline test generation** — produce scenarios and expected trajectories;
2. **online/replay evaluation** — interpret and evaluate actual agent behavior.

That dual use is arguably the most important architectural opportunity in the current POC.

---

## 17. Important distinction: scenario generation vs GT resolution

These should remain conceptually separate.

**Scenario generation** starts with the KG and creates a controlled test case. Purpose: coverage;
branch exploration; enrichment; reproducibility; designed experiments.

**GT resolution for an actual trace** starts with an observed agent state and asks: *what does the
policy say should happen here?* Purpose: production/replay evaluation; continuous monitoring;
evaluation without pre-authored scenarios; diagnosis of observed behavior.

The KG is the common knowledge source, but the entry points are different.

---

## 18. The most important implementation reuse opportunity

The POC should not grow a completely separate reverse-oracle architecture. Instead, reuse the
existing pieces — `GraphReader`, `PathResolver`, `RuleCompiler`, `GroundTruthExtractor` concepts —
and generalize them from:

```python
extract_ground_truth(scenario)
```

to support something conceptually like:

```python
resolve_ground_truth_from_observed_turn(observed_turn)
```

The scenario path and turn-level record already contain most of the information the new resolver
will need. The new resolver is therefore a **different entry point into the same policy graph**, not
an entirely new GT engine.

---

## 19. Recommended turn-level contract

```
identity
- voicebot_id
- step_id
- turn_id
- occurrence / sequence if available

expected behavior
- expected actor
- expected response behavior / canonical text
- generated_allowed

expected action
- expected tool
- allowed tool outcomes
- expected tool attempt number

state
- state before
- expected state after
- expected next step

rules
- applicable Rule IDs
- compiled predicates where available

provenance
- KG version
- source rule IDs
```

This is enough for initial evaluation without implementing the full book.

---

## 20. Evaluation strategy for the current POC

**Tool correctness** — keep deterministic. Compare expected tool, expected attempt number, expected
outcome where appropriate.

**Response correctness** — use an LLM judge, but give it the policy context and the resolved KG
contract. The judge should answer: *Does this actual response satisfy the required behavior at this
exact state/turn under the governing policy?*

> Do not make the judge the source of truth. The judge is a semantic comparison mechanism operating
> **on top of KG-derived truth**.

---

## 21. Why this is stronger than plain expected-text comparison

The KG can say: `"I am sorry, I could not verify your details. Please try again."`
An agent might say: `"I wasn't able to verify your information. Please retry."`
Exact-match would fail; the policy meaning is preserved, so an LLM judge can mark it correct.

Conversely, an agent could produce `"Your authentication was successful; I will transfer you now."`
after a failed authentication result. A semantic judge seeing the resolved KG contract and tool state
can flag the grounding violation.

Thus the judge is evaluating **behavioral semantics**, not surface similarity.

---

## 22. What would need to change in the KG

The existing graph may be enough for the first experiment, but reverse lookup could become easier if
more semantics are represented structurally rather than only in free-text `NEXT.when` strings.

Instead of only:

```
NEXT {when: "authenticate_customer returns FAILED AND attempt_count < 3"}
```

a richer representation could encode: outcome = `FAILED`; attempt condition = `<3`; destination =
`retry`.

Likewise, turn nodes could more explicitly encode expected action, allowed outcomes, and required
state predicates.

The reason is not that the graph is currently insufficient — it is that structured predicates reduce
dependence on a Python condition interpreter and make reverse resolution more generic. This should
be treated as an incremental schema improvement, not a prerequisite.

---

## 23. Current limitations and caveats

1. **Procedural graph is domain-specific.** The current `RuleCompiler` knows a fixed set of
   authentication-domain rule codes. It is not yet a generic arbitrary-policy compiler.
2. **Conditions are partly interpreted in Python.** The graph stores natural-language-ish transition
   conditions, while Python knows how to interpret the current vocabulary.
3. **Response semantics are not graph-native.** The graph has canonical text and generated-allowed
   flags, but semantic paraphrase evaluation is delegated to an LLM judge.
4. **Raw utterance-to-state matching is unresolved.** If step/turn metadata is available, this is
   easy. If absent, a semantic binding mechanism is required.
5. **The current POC is not a GMS implementation.** The graph includes `embedding_text` fields, but
   these are not the book's learned geometric memory — no learned v-space/u-space, calibrated
   geometry, holonomy, tension energy, etc.
6. **Scenario generation is stronger than live evaluation today.** The current code is more mature
   for precomputed scenarios than for direct live-trace resolution. The reverse evaluator is
   therefore the logical next architectural increment.

---

## 24. A simple end-state architecture

```
                         POLICY DOCUMENT
                                |
                                v
                         PROCEDURAL KG
                                |
          +---------------------+---------------------+
          |                                           |
          v                                           v
   SCENARIO GENERATOR                          KG STATE RESOLVER
          |                                           |
          v                                           v
   Scenario + GT                              Turn-level GT Contract
          |                                           |
          |                         +-----------------+----------------+
          |                         |                                  |
          v                         v                                  v
    Test / Simulator          Tool Evaluation                  Response Evaluation
          |                         |                                  |
          +-------------------------+----------------------------------+
                                    |
                                    v
                              Evaluation Results
```

The same KG becomes the **common policy backbone** for both synthetic testing and actual-agent trace
evaluation.

---

## 25. How to think about the bigger picture

- **Stage 1 — policy as document.** Humans read policy prose and manually reason about expected
  agent behavior.
- **Stage 2 — policy as procedural KG.** The document is converted into structured steps, turns,
  tools, outcomes, transitions and rules.
- **Stage 3 — KG as scenario oracle.** The KG generates legal paths and precomputed ground truth for
  controlled scenarios.
- **Stage 4 — KG as trace oracle.** An actual observed agent state is mapped back to the KG and the
  applicable contract is reconstructed dynamically.
- **Stage 5 — KG + semantic verifier.** An LLM or GMS evaluates natural-language claims against that
  KG-derived contract.
- **Stage 6 — continuous governed evaluation.** The same policy representation supports synthetic
  scenario generation, replay evaluation, production trace monitoring, regression test creation,
  failure attribution and policy-change impact analysis.

> This is the larger opportunity: the KG stops being merely a tool for designing benchmark scenarios
> and becomes a **shared executable representation of the policy that defines what correct agent
> behavior means**.

---

## 26. Open questions before implementing reverse GT

**A. What metadata does the real agent provide?** Can we reliably receive current step, turn ID,
state, tool call, tool result, attempt number, sequence/occurrence, terminal status? If yes, reverse
lookup is mostly deterministic. If no, what must be inferred from text?

**B. What is the minimum turn-level GT contract?** Possible fields: expected response behavior;
expected tool/action; allowed outcome; next state; state invariants; applicable rules. The contract
should be minimal but sufficient for the metrics we actually intend to run.

**C. Where should semantic resolution happen?** If metadata is missing, do we want an LLM resolver;
embeddings; graph aliases; eventually GMS fuzzy matching? This should be separated from core GT
logic.

**D. How much of the rule language should remain in Python?** For the POC, a small interpreter is
acceptable. Longer term, more transition/action predicates may be better represented structurally in
the KG.

**E. When is GMS actually justified?** A sensible trigger is when we need capabilities the symbolic
graph + LLM judge cannot provide reliably: graded semantic plausibility; contradiction; multi-hop
consistency; calibrated acceptance thresholds; large-scale semantic entity binding.

---

## 27. Key conclusions to carry forward

1. **The book and the POC are related but not equivalent.** The book implements a full GMS-backed
   methodology; the POC intentionally implements a simpler procedural KG + Oracle approach.
2. **The POC's KG is more than a flowchart.** It contains workflow states, turns, tools, outcomes,
   transitions and governing rules, which makes it capable of defining expected agent behavior.
3. **The current `GroundTruthExtractor` already does a large part of what reverse evaluation needs.**
   It resolves a legal path, expands turn occurrences, carries state, and compiles rules into
   assertions.
4. **Reverse evaluation should reuse the same graph semantics.** The new capability should resolve a
   turn contract from observed metadata rather than building an entirely new ground-truth system.
5. **GMS is not automatically required.** For known step/turn/state/tool metadata, most ground truth
   can be retrieved and reasoned over deterministically from the current graph.
6. **LLM judging is appropriate for natural-language response semantics, not for defining truth.**
7. **The hard unresolved problem is raw-text-to-state binding.** If a real trace lacks reliable
   step/turn metadata, semantic matching is required before GT can be resolved.
8. **The broader architectural opportunity is dual-use of the KG:** one policy backbone supporting
   both scenario generation and evaluation of actual agent traces.
9. **The most useful next prototype is small:** take one observed turn with metadata, resolve its KG
   state, produce a turn-level contract, and evaluate the actual tool call deterministically and the
   response with an LLM judge.

---

## 28. Source grounding for this strategy brief

The book source used for the methodology portions is *Beyond "Ship and Pray": Testing Agentic Systems
with Geometric Ground Truth*, which defines the baseline KG, GMS capabilities, oracle construction,
scenario design, enrichment, agent trajectory evaluation, and the capstone governed-agent workflow.

The POC-specific implementation details come from the supplied repository, including:

- `knowledge_graph/data/02_card_authentication_graph.cypher`
- `src/voicebot_eval/oracle/graph_reader.py`
- `src/voicebot_eval/oracle/path_resolver.py`
- `src/voicebot_eval/oracle/rule_compiler.py`
- `src/voicebot_eval/oracle/ground_truth.py`
- `src/voicebot_eval/schemas/oracle.py`
- `src/voicebot_eval/scenarios/inspection.py`
- `notebooks/15_scenario_inspector.ipynb`
- the simulator notebooks and card-authentication simulator implementation
- the supplied card-authentication operating procedure and implementation blueprint

The strategic reverse-GT proposal is an architectural inference from those artifacts rather than a
literal implementation already present in the repository.
