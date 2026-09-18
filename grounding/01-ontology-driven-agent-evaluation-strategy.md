# Ontology-Driven Agent Evaluation — Consolidated Strategy

> **Source:** Internal discussion notes, prepared September 2026.
> Consolidated from the Scenario Generator codebase, eval-poc, the strategy handover,
> *Beyond "Ship and Pray"*, and external agent-evaluation research.
>
> **Status in this repo:** grounding document. This is the target-state strategy the
> Scenario Generator is being re-architected against.

---

## Executive summary

### Core strategic position

Use a versioned ontology as the normative mapping of policy into machine-readable concepts,
states, actions, tools, rules, conditions and evidence. Compile that ontology into executable
evaluation contracts. Scenario generation and observed-trace evaluation should be two entry
points into the same ground-truth resolver and evaluator. GMS, or an internally developed
equivalent, should be a replaceable semantic-verification backend rather than a prerequisite
for the architecture.

The work reviewed here is not three competing strategies. It is better understood as three
partially overlapping layers of one stronger solution. The Scenario Generator is strongest at
discovering and structuring the test space. The procedural-KG eval POC is strongest at turning
policy into occurrence-level executable expectations. The KnowlytiX/GMS methodology adds a
sophisticated oracle, controlled enrichment, designed experiments, semantic verification and
failure attribution. External work such as τ-bench, ToolSandbox, Ragas and current
agent-evaluation guidance reinforces the value of stateful environments, outcome verification,
milestones, knowledge-graph-driven synthesis and mixed deterministic/model-based grading.

The recommended product is therefore an **Ontology-Driven Agent Evaluation & Ground Truth
Platform**. Its core asset is not a benchmark dataset and not a judge model. Its core asset is a
versioned executable policy representation that can answer two symmetrical questions:

1. Given policy, what situations should be tested and what should be true in each?
2. Given an observed agent trace, what policy-derived contract applies here and did the
   behavior satisfy it?

### Major bottom-line facts

- Ontology is the backbone, but ontology alone is not ground truth. It must be compiled into
  executable obligations, permissions, prohibitions, transition conditions, invariants,
  milestones and terminal-state predicates.
- Scenario generation and live/replay trace evaluation should share one `GroundTruthResolver`
  and one `EvaluationContract` schema.
- Ground truth should be contract-based rather than answer-based: it should specify valid
  states, required/forbidden actions, allowed flexibility, milestones and acceptable terminal
  outcomes.
- Deterministic checks should establish truth wherever possible. LLMs should interpret
  natural-language behavior relative to that truth, not define the truth.
- The evaluator should be state- and policy-satisfaction-oriented, not merely an exact
  trajectory matcher. Fixed workflows can still use strict order checks as a special case.
- GMS is valuable for fuzzy entity binding, graded claim plausibility, contradiction, path
  consistency and calibrated semantic decisions, but the proprietary implementation is not
  required to establish the overall architecture.
- The architecture should expose semantic-oracle primitives so a GMS-like implementation can be
  added later without redesigning scenario generation, GT resolution or evaluation.
- Comprehensive evaluation should remain multidimensional: outcome, policy, state, trajectory,
  tool use, grounding/provenance, resilience and operational health should be measured
  separately before any roll-up.
- Coverage must be measurable against the ontology: rules, states, transitions, tools,
  capabilities, outcomes, perturbations and fault conditions should all have explicit coverage
  metrics.
- Every GT assertion must be auditable back to policy evidence, ontology/rule version and
  derivation method.

---

## 1. Problem definition and design principles

### 1.1 The problem to solve

The target is broader than synthetic test generation. The desired solution should automatically
construct trustworthy ground truth from approved policy/requirements, generate comprehensive and
risk-relevant scenarios, evaluate agent behavior at outcome and trajectory levels, and explain
failures in a way that can be traced to policy and system components. It should work both before
deployment and on replayed/observed traces after deployment.

A benchmark-style "prompt → expected answer → score" abstraction is insufficient for agents
because agents operate over multiple turns, call tools, modify state, branch, retry, escalate and
sometimes have several valid ways to reach the same compliant outcome. Current external guidance
similarly distinguishes the full transcript/trajectory from the final environment outcome and
recommends multiple graders over different aspects of behavior.

> **Source note:** Anthropic, "Demystifying evals for AI agents" (2026), distinguishes tasks,
> trials, graders, transcripts, outcomes and evaluation harnesses; it recommends code-based,
> model-based and human graders depending on what is being measured.

### 1.2 Design principles

| Principle | Meaning |
|---|---|
| Policy remains authoritative | Models may assist extraction, binding, realization and semantic comparison, but approved policy and approved structured representations determine normative truth. |
| Truth and judging are separate | A judge may decide whether free-form behavior satisfies a contract; it must not invent the contract. |
| One specification, two entry points | Synthetic scenarios and observed traces should resolve against the same ontology/rules and produce the same contract type. |
| Deterministic first | Use code/rules/state assertions for tools, values, counters, transitions, ordering and terminal states before using model-based graders. |
| Allow legitimate agent flexibility | Evaluate invariants, milestones and outcomes unless a fixed order is itself a policy requirement. |
| Version everything | Policy, ontology, executable rules, GT contracts, semantic-oracle models and evaluator logic must be reconstructable. |
| Uncertainty is explicit | State binding, semantic matching and extraction confidence should be represented, not hidden. |
| Coverage is a product output | A campaign should report what policy and ontology space was covered and what remains untested. |
| Failure output must be actionable | A failure should map to a violated assertion, governing rule, source evidence and, where possible, responsible component. |
| Semantic verification is pluggable | GMS, embeddings, NLI/classifiers and LLM judges should sit behind stable oracle interfaces. |

---

## 2. What the existing assets already provide

### 2.1 Scenario Generator: the test-space compiler foundation

The Scenario Generator codebase already has a strong deterministic representation of agent
structure. Its core dataclasses include `Capability`, `Decision`, `State`, `Persona` and `Tool`.
A `Decision` declares variants, input source, retry limits and outcome conditions. A `State`
records how it is reached, which decisions can follow, whether it is terminal and its outcome
type. A `Tool` is associated with a capability and can be marked state-changing. This is already
an ontology-like application model, even though it is not yet a full policy ontology.

A particularly important design decision is capability-scoped enumeration. The code comments
explicitly explain that walking an entire multi-capability agent end-to-end creates combinatorial
explosion and many scenarios that differ only in how an earlier block was entered. Capabilities
therefore define entry and exit states, and the graph is enumerated in bounded spans. This is a
strong foundation for a practical enterprise test-space compiler.

The `Scenario` object also already carries useful GT-adjacent metadata: seeded state, precondition,
termination, touched capabilities/tools, state-change indicator and `TurnMeta`. `TurnMeta` captures
decision id/name, expected variant, expected tool, next state and input source. The strategic gap
is not lack of structure; it is that this structure needs to be generalized into a richer
executable behavioral contract.

> **Implication:** Do not rewrite the Scenario Generator as a new benchmark framework. Preserve
> its deterministic graph, capability scoping, variant coverage, probe model, materiality and
> provenance. Evolve its output from "scenario + expected path metadata" into "scenario +
> executable EvaluationContract + coverage metadata".

### 2.2 eval-poc: the executable-oracle foundation

The procedural-KG POC complements the Scenario Generator. Its graph models steps, turns, tools,
outcomes, transitions and rules. The `GroundTruthExtractor` resolves a scenario path, gathers rules
from visited steps/turns/tools, compiles rules into atomic `GroundTruthAssertion` objects,
constructs expected tool calls and expands graph turn definitions into occurrence-level
`TurnGroundTruth` records.

`TurnGroundTruth` is a strong seed for the mature contract model because it includes occurrence
identity, sequence, step and turn, actor, expected text, expected tool call/result, expected next
step, state before/after and assertion IDs. The `GroundTruth` object then adds expected steps, tool
calls, turns, outcomes, assertions, oracle version, KG version and source-rule IDs.

> **Source note:** `WHOLE_STRATEGY_BRIEF_FOR_AI.md` describes the POC as a procedural Neo4j KG plus
> GroundTruthOracle and explicitly proposes evolving from scenario-first evaluation to
> agent-trace-first evaluation. See especially sections 1, 5, 10–19 and 27.

### 2.3 Beyond "Ship and Pray" / KnowlytiX methodology

The book contributes three ideas that are especially valuable even if the proprietary GMS
implementation cannot be reused. First, it separates a base item carrying content and ground truth
from ground-truth-invariant enrichment factors that vary presentation. Second, it treats agent
evaluation as component, system, operational and resilience testing over trajectories rather than
only answer accuracy. Third, it uses controlled experimental design and statistical attribution to
identify the conditions under which failures concentrate.

The GMS-specific layer adds exact reads, exact numeric memory, graded triple plausibility,
contradiction/tension, path consistency/holonomy, entity matching and calibrated operating points.
These are best treated as semantic-oracle capabilities rather than mandatory architecture
components.

> **Source note:** *Beyond "Ship and Pray"* chapters 1–4 define correct-by-construction ground
> truth, graph/exact memory, GMS primitives and oracle construction; chapters 5–8 define base
> categories, enrichment and experimental design; chapters 9–12 define trajectory-level agent
> testing, attribution and resilience.

---

## 3. External strategies and what to borrow

| Approach | Core pattern | What to borrow |
|---|---|---|
| τ-bench | Dynamic user-agent-tool interaction; compares final database state to annotated goal state; pass^k captures consistency. | Adopt environment/state outcome verification and repeated trials for stochastic agents. |
| ToolSandbox | Stateful tool execution, implicit state dependencies, conversational simulation, dynamic intermediate/final milestone evaluation over arbitrary trajectories. | Adopt milestone-based evaluation and state dependencies instead of one canonical path. |
| Ragas | Builds/enriches a KG from documents, traverses it to generate scenarios, and varies query type/style/persona. | Adopt KG-driven synthesis patterns and keep scenario realization separate from the source of truth. |
| Anthropic agent-eval guidance | Defines task/trial/grader/transcript/outcome/harness and recommends code-, model- and human-based graders. | Adopt grader layering, transcript review, repeated trials and outcome-vs-transcript distinction. |
| KnowlytiX methodology | Oracle-grounded bases + GT-invariant factors + designed experiments + multi-level agent scoring. | Adopt base/enrichment separation, coverage design, attribution and resilience; treat GMS as optional backend. |

> **Source note:** Web research used for this document: τ-bench arXiv 2406.12045; ToolSandbox
> Findings of NAACL 2025; Ragas testset-generation documentation; Anthropic "Demystifying evals for
> AI agents," Jan. 9, 2026.

---

## 4. Target conceptual model

> **Target product:** Ontology-Driven Agent Evaluation & Ground Truth Platform — a
> policy-to-evaluation compiler that turns approved policy into versioned executable
> specifications, generates controlled tests, resolves ground truth for observed traces, and
> evaluates agents with deterministic and semantic graders.

```
POLICY / PROCEDURE / REQUIREMENTS
            |
            v
   POLICY + AGENT ONTOLOGY
            |
            v
    EXECUTABLE SPECIFICATION
      /                 \
     v                   v
SCENARIO GENERATOR   TRACE/STATE BINDER
     |                   |
     +---------+---------+
               v
      GROUND TRUTH RESOLVER
               |
               v
       EVALUATION CONTRACT
               |
               v
        HOLISTIC EVALUATOR
   outcome | policy | state | tools
 trajectory | grounding | resilience
               |
               v
 coverage + attribution + evidence
```

### 4.1 Separation of concerns

| Layer | Responsibility | Must not do |
|---|---|---|
| Policy source | Authoritative human-approved source text and artifacts. | Depend on generated summaries as the only evidence. |
| Ontology | Canonical concepts, relations, states, actions, tools, rule vocabulary and source mappings. | Decide semantic correctness of arbitrary free-form text by itself. |
| Executable specification | Machine-checkable predicates, transitions, constraints, milestones and terminal conditions. | Hide business rules in opaque prompts. |
| Scenario generator | Select and compose meaningful test conditions; realize controlled test inputs. | Become the source of truth for policy. |
| GT resolver | Instantiate applicable contract from scenario or observed trace. | Use the agent-under-test response as truth. |
| Evaluator | Apply deterministic/semantic graders to trace and outcome. | Silently infer missing state without confidence/provenance. |
| Semantic oracle | Resolve fuzzy language, claims and contradictions with calibrated confidence. | Own the overall architecture or replace exact rule checks. |

---

## 5. Ontology design

The ontology should be broader than a traditional domain taxonomy. It should provide a common
vocabulary for policy, agent behavior, runtime state and evaluation. The recommended model has
five linked layers.

| Ontology layer | Representative concepts | Why needed |
|---|---|---|
| Domain | Customer, account, card, transaction, dispute, regulation, policy object. | Ground facts and policy subjects/objects. |
| Agent | Capability, decision, action, tool, turn, sub-agent, escalation, memory operation. | Describe what the system can do. |
| State | State variable, value, precondition, postcondition, counter, terminal state. | Make runtime truth and transitions explicit. |
| Policy / deontic | Obligation, permission, prohibition, exception, threshold, sequence, scope, severity. | Translate prose into normative behavior. |
| Evaluation | Assertion type, grader type, milestone, outcome, coverage item, confidence, provenance. | Make testing itself machine-readable and portable. |

### 5.1 Minimum ontology relations

- `CAPABILITY_HAS_DECISION`
- `STATE_ALLOWS_DECISION`
- `DECISION_HAS_OUTCOME`
- `OUTCOME_TRANSITIONS_TO_STATE`
- `ACTION_USES_TOOL`
- `RULE_GOVERNS_{STATE|ACTION|TOOL|TURN}`
- `RULE_REQUIRES` / `RULE_FORBIDS` / `RULE_PERMITS`
- `RULE_HAS_CONDITION` / `EXCEPTION` / `THRESHOLD`
- `FACT_DERIVED_FROM_SOURCE_SPAN`
- `MILESTONE_REQUIRES_ASSERTION`
- `TERMINAL_STATE_SATISFIES_OUTCOME`
- `ALIAS_OF` / `REFERS_TO`
- `SUPERSEDES` / `VERSION_OF`

### 5.2 Ontology quality requirements

- Every evaluation-relevant concept has a stable ID independent of display text.
- Every normative rule links to source evidence and a policy version.
- Transition conditions are structured predicates rather than only natural-language "when" strings.
- Exact numeric/enum values are stored as typed data, not reparsed from prose during evaluation.
- Aliases and canonical names are explicit to support trace binding.
- Rules can be scoped to state, action, tool, turn, capability, conversation or whole journey.
- Conflicts and unresolved extractions are representable states; they are not silently reconciled.
- Ontology changes produce impact reports identifying affected scenarios, rules and evaluation
  contracts.

---

## 6. Policy-to-ontology and policy compiler

### 6.1 Ingestion pipeline

```
Approved source artifacts
        |
        v
Deterministic parsing / document structure
        |
        v
Candidate entities, states, rules, values, evidence spans
        |
        v
LLM-assisted normalization / relation extraction (optional)
        |
        v
Schema + evidence validation
        |
        v
Human review for unresolved/high-impact items
        |
        v
Versioned ontology + exact value store + rule specification
```

The current Scenario Generator grounding philosophy should be retained: models can propose
interpretations, but evidence presence and schema consistency should be deterministically checked.
For high-impact rules, approval should be explicit. A future semantic oracle can help identify
contradictions or suspicious extractions, but it should not silently repair policy meaning.

### 6.2 Policy rule DSL

The mature system needs a small rule language or typed assertion model. This is preferable to a
domain-specific Python `RuleCompiler` that grows indefinitely. The DSL can be declarative
JSON/YAML backed by typed code.

```yaml
rule_id: MAX_AUTH_ATTEMPTS
scope: authentication
kind: count_constraint
when:
  state.authenticated: false
assert:
  count(tool.authenticate_customer) <= 3
severity: error
source:
  policy_version: v17
  section: authentication.retry
  evidence_span_id: span_0042
```

```yaml
rule_id: FAILED_AUTH_TRANSITION
scope: authentication
kind: conditional_transition
when:
  observation.auth_result: FAILED
  state.attempt_count: "< 3"
assert:
  next_state: retry
  required_behavior: communicate_auth_failure
source: ...
```

### 6.3 Generic assertion primitives

| Primitive | Typical use |
|---|---|
| StateAssertion | A state variable/value must hold before, during or after an event. |
| TransitionAssertion | A given condition permits/requires a specific next state. |
| ActionAssertion | An action is required, allowed or forbidden. |
| ToolAssertion | Tool identity, arguments, result or invocation count. |
| SequenceAssertion | A must precede/follow B; ordered process. |
| CountAssertion | Retries, calls, occurrences or limits. |
| ValueAssertion | Exact numeric, enum or categorical fact. |
| Existence/AbsenceAssertion | Required event/fact exists or prohibited event/fact does not. |
| ConditionAssertion | If condition C holds, expectation E applies. |
| MilestoneAssertion | A semantic/process milestone must be achieved. |
| TerminalAssertion | Final state belongs to acceptable terminal set. |
| GroundingAssertion | A generated claim must be supported by policy/knowledge. |
| ProvenanceAssertion | A claim/evaluation must point to valid source evidence. |
| GovernanceAssertion | Escalation, refusal, disclosure or authorization behavior. |

---

## 7. Evaluation Contract and GroundTruthResolver

### 7.1 The EvaluationContract as the central artifact

```
EvaluationContract
  identity
    contract_id, policy_version, ontology_version, evaluator_version
  binding
    scenario_id OR trace_id, resolved_state, binding_confidence
  initial_state
    typed facts, counters, permissions, tool availability
  required_behavior
    required actions, semantic obligations
  allowed_behavior
    acceptable alternatives / flexible actions
  forbidden_behavior
    prohibited actions, claims, tools, transitions
  milestones
    required, optional, forbidden; ordering/dependency constraints
  transitions
    preconditions, observations, postconditions
  terminal_conditions
    acceptable end states and escalation conditions
  assertions[]
    type, scope, expected, severity, grader, provenance
  provenance
    source spans, rule ids, derivation method
  confidence
    binding/semantic confidence where non-deterministic
```

### 7.2 Two symmetrical resolution APIs

```python
resolve_for_scenario(scenario, ontology_version) -> EvaluationContract
resolve_for_trace(observed_trace, ontology_version) -> EvaluationContract
```

The first path compiles a generated scenario into its applicable policy contract. The second binds
an observed trace/state to the ontology and resolves the contract that should have applied. Both
must call the same underlying rule/state engine. This prevents the synthetic benchmark from
drifting away from production evaluation.

### 7.3 Ground-truth ladder

| Level | Ground-truth provenance | Use |
|---|---|---|
| L0 | Human supplied expectation | Legacy/manual cases; lowest automation. |
| L1 | Direct policy-derived structured rule | Approved extraction with source evidence. |
| L2 | Ontology/rule-derived expectation | Deterministic graph/rule resolution. |
| L3 | Executable-state-derived outcome | Policy + current state + tool/action semantics. |
| L4 | Semantic-oracle verified | Fuzzy claim/entity/path verified with calibrated semantic mechanism. |
| L5 | Independently validated | Cross-checks and/or human adjudication for high-impact cases. |

Each assertion should record its derivation level. This gives governance reviewers a direct answer
to "how was this ground truth established?"

---

## 8. Scenario generation and controlled enrichment

### 8.1 Base scenario generation

The existing `DecisionGraph`/capability-span machinery should remain the primary generator of
structural behavioral cases. The generator should enumerate legal paths within capability
boundaries, add uncovered decision/variant combinations, identify terminal and unreachable
elements, and attach materiality. Each base scenario should then be compiled into an
`EvaluationContract`.

### 8.2 Separate base truth from presentation variation

Adopt the book's base/enrichment separation. A base scenario fixes the underlying policy situation
and expected contract. Enrichment varies the way the agent encounters that situation without
changing the truth. This provides controlled robustness testing without relabeling every variant.

| Factor family | Examples |
|---|---|
| Language/presentation | clarity, length, paraphrase depth, formality, ambiguity |
| Persona | novice/expert, role, communication style |
| Conversation | history depth, distracting prior turns, turn position |
| Channel/noise | ASR corruption, typos, OCR artifacts, malformed formatting |
| Context | relevant/irrelevant context, ordering, wrong hints, missing context |
| Adversarial | instruction conflict, answer anchoring, confidence pressure |
| System envelope | tool availability, iteration budget, time pressure |
| Faults | timeout, exception, stale data, malformed output, plausible-but-wrong output |

> **Source note:** *Beyond "Ship and Pray"* defines 40 ground-truth-invariant enrichment factors
> across query, persona, reasoning, context, entity/value, conversation, adversarial, system,
> variability and robustness groups. Ragas similarly varies query style/length/persona over
> KG-selected content.

### 8.3 Sampling strategy

Do not full-factorially cross every scenario with every factor. Recommended maturity path:
pairwise/covering-array designs first; then risk-weighted coverage using materiality; then
Sobol/space-filling designs if statistical factor attribution becomes a key requirement.
High-materiality cases should receive more perturbation combinations, repeated stochastic trials
and fault injections.

---

## 9. Trace-first evaluation

### 9.1 Required trace envelope

| Field | Why it matters |
|---|---|
| event/sequence id | Reconstruct order and occurrence identity. |
| timestamp | Latency, ordering and stale-state checks. |
| agent/sub-agent id | Attribute actions in multi-agent systems. |
| state id + state variables | Avoid inferring runtime state from prose. |
| user/system input | Semantic context and replay. |
| agent response | Communication/claim evaluation. |
| tool call + arguments | Deterministic action grading. |
| tool result | Branch/state validation. |
| memory reads/writes | Stateful-agent correctness and contamination checks. |
| terminal status / escalation | Outcome and process health. |
| policy/agent version | Reproducibility. |

### 9.2 State binder

If the trace exposes reliable state/turn metadata, binding should be deterministic. If metadata is
absent, a separate `StateBinder` should infer candidate ontology states/entities from text and
return confidence and alternatives. Binding uncertainty must not be hidden inside the evaluator.

```
StateBinding
  canonical_state: authentication_retry
  confidence: 0.84
  evidence: [tool_result=FAILED, attempt_count=2, utterance_semantics]
  alternatives:
    - authentication_initial: 0.11
    - max_retry: 0.05
```

> **Key requirement:** A low-confidence state binding should be surfaced as evaluation uncertainty
> or routed for adjudication; it should not silently become a hard ground-truth verdict.

---

## 10. Holistic evaluation and failure attribution

### 10.1 Evaluation dimensions

| Dimension | Core question | Preferred grader |
|---|---|---|
| Outcome | Did the task reach an acceptable terminal state? | State/environment check |
| Policy | Were obligations/prohibitions/permissions respected? | Rule assertions |
| State | Were pre/post conditions and counters correct? | Deterministic |
| Trajectory | Were required milestones/dependencies/order satisfied? | Deterministic + milestone |
| Tool | Were tool choice, arguments and outcomes handled correctly? | Deterministic |
| Grounding | Are factual/policy claims supported? | Exact + semantic oracle |
| Provenance | Can claims/verdicts be traced to valid source evidence? | Deterministic |
| Communication | Did free-form language satisfy required meaning? | Constrained semantic judge |
| Resilience | Did the agent detect/recover/escalate under faults? | Fault injection + state checks |
| Operational health | Loops, unnecessary calls, latency, cost, termination. | Trace metrics |

### 10.2 Do not force a single score too early

Store and report the dimensions independently. A later deployment gate may define hard blockers and
weighted summaries, but the raw dimensions are necessary for diagnosis. For example, a run may reach
the right outcome while violating a policy rule, or fail the final outcome despite correct tool
behavior. Collapsing both to one score loses the distinction.

### 10.3 Failure attribution

```
Observed failure
      |
      v
first violated assertion
      |
      +--> governing rule --> policy evidence
      |
      +--> trace event / state transition
      |
      +--> component / tool / planner / semantic layer
      |
      v
failure family + materiality + perturbation context
```

At campaign level, aggregate failures by policy rule, capability, state, component and enrichment
factor. If controlled factor designs are used, logistic or related models can estimate which
conditions materially change failure probability. The book's weak-link decomposition — charging a
failed run to the first graded component that erred — is a useful diagnostic complement to factor
attribution.

---

## 11. Semantic oracle and GMS / GMS-lite

### 11.1 What GMS is useful for

The GMS concepts are most valuable where symbolic graph traversal stops being enough: fuzzy entity
binding, graded claim plausibility, contradiction, semantic stance, path consistency and calibrated
acceptance/abstention. These should be represented as required oracle capabilities, not as a
dependency on one proprietary implementation.

### 11.2 Stable semantic-oracle interface

```python
interface SemanticOracle:
  resolve_entity(text, context) -> candidates + confidence
  verify_claim(claim, policy_context) -> supported/contradicted/uncertain + score
  detect_contradiction(claim_a, claim_b) -> score + decision
  verify_path(path, direct_relation=None) -> consistency score
  calibrate(dataset, target_false_accept_rate) -> operating_points
```

### 11.3 GMS-lite implementation path

| Capability | V1 practical implementation | Potential advanced/GMS-like implementation |
|---|---|---|
| Exact memory | Typed key/value store + source span + hash. | Same; exact facts should remain exact. |
| Entity binding | Aliases + embeddings + reranker + confidence. | Document/domain-tuned semantic channel. |
| Claim grounding | Parse typed claim; exact KG lookup; NLI/reranker/LLM for paraphrase. | Calibrated relation-conditioned geometric score. |
| Contradiction | Typed oppositions + NLI contradiction classifier. | Logical embedding/tension-like score. |
| Path consistency | Symbolic graph/path rules and invariant checks. | Learned/geometric composition consistency. |
| Calibration | Held-out labeled cohorts; reliability curves; threshold by risk target. | Per-relation calibrated operating points. |

### 11.4 When full GMS-like work is justified

- Symbolic + embedding + semantic judge produces too many ambiguous claim decisions.
- Entity/turn binding at production scale is a dominant error source.
- Contradiction or policy-stance reversals cannot be robustly handled with typed rules/NLI.
- Multi-hop inferred claims need a calibrated consistency measure beyond explicit graph rules.
- A known false-accept rate for semantic decisions is a governance requirement.
- The expected improvement can be measured against a labeled validation cohort.

> **Decision rule:** Build the deterministic ontology/rule/state platform first. Add GMS-like
> capabilities only for demonstrated semantic gaps. This preserves the value of GMS without making
> proprietary internals a blocker.

---

## 12. Coverage, governance and lifecycle

### 12.1 Coverage model

| Coverage family | Examples |
|---|---|
| Ontology | entities, relations, rules, exact values |
| Behavioral topology | capabilities, decisions, variants, states, transitions, terminal states |
| Tools | tool identity, arguments, result branches, state-changing calls |
| Policy | obligations, prohibitions, permissions, exceptions, thresholds |
| Scenarios | base paths, boundaries, negative cases, escalation cases |
| Enrichment | factor levels and selected pair/interactions |
| Resilience | fault type × tool/component × recovery behavior |
| Trace evaluation | states/turns for which reverse GT was successfully resolved |

### 12.2 Coverage gaps are first-class outputs

- Unreachable ontology states or transitions.
- Declared rules with no executable assertion compiler.
- Rules never exercised by any scenario.
- Tools with no failure-injection coverage.
- High-materiality states with insufficient stochastic trials.
- Semantic assertions with no calibrated grader.
- Observed production states that cannot be bound confidently to the ontology.
- Policy source spans that no longer match the current source artifact.

### 12.3 Change management

Policy and ontology should have separate linked versions. A policy change should trigger
extraction/review, ontology/rule diffs, affected-scenario identification, GT-contract regeneration
and targeted regression execution. Agent changes should trigger the relevant suite against the same
policy version. Semantic-oracle changes should be versioned and regression-tested independently
because changing the grader can change apparent agent quality.

---

## 13. Requirements

### 13.1 P0 functional requirements

- Ingest approved policy/procedure artifacts and retain source-level provenance.
- Represent domain, agent, state, policy and evaluation concepts in a versioned ontology.
- Compile policy rules into typed executable assertions and structured transition conditions.
- Store exact numeric/enum facts as typed values with provenance.
- Generate structural base scenarios from ontology/decision/state topology.
- Produce an `EvaluationContract` for every generated scenario.
- Accept an observed trace and resolve an `EvaluationContract` without requiring a pre-generated
  scenario.
- Deterministically grade tools, arguments, state, counters, transitions, ordering and terminal
  conditions where applicable.
- Return failure explanations linked to violated assertions and source rules.
- Report ontology/policy/scenario coverage and unresolved gaps.
- Version policy, ontology, rules, contracts and evaluator logic.

### 13.2 P1 functional requirements

- Support ground-truth-invariant enrichment factors and controlled scenario realization.
- Support fault injection for hard errors, timeout/latency, stale data, malformed results and
  plausible-but-wrong results.
- Support milestone-based trajectory evaluation in addition to strict fixed-workflow adherence.
- Support semantic response/claim grading against a resolved contract.
- Support repeated trials and reliability metrics for stochastic agents.
- Support component-level and factor-level failure attribution.
- Support policy-change impact analysis and targeted regression suite generation.
- Support human adjudication queues for low-confidence or high-impact semantic cases.

### 13.3 P2 requirements / advanced semantic oracle

- Calibrated entity/state binding confidence.
- Calibrated semantic claim groundedness.
- Contradiction and stance verification.
- Path/composition consistency for inferred claims.
- Per-relation or per-rule operating points with measured false-accept/false-reject behavior.
- Pluggable GMS or internally developed geometric/representation-learning backend.

### 13.4 Non-functional requirements

| Requirement | Expectation |
|---|---|
| Auditability | Every verdict reconstructable from trace + contract + rule + source + versions. |
| Reproducibility | Deterministic graders replay identically; stochastic graders log model/config and confidence. |
| Explainability | Failure reason is assertion-level, not only a score. |
| Security/privacy | Sensitive trace/policy data controlled; redaction and access controls where required. |
| Scalability | Capability-scoped generation; incremental recompilation; batch trace evaluation. |
| Extensibility | New domains add ontology/rules rather than fork evaluator code. |
| Testability | Oracle and grader components have independent unit/golden tests. |
| Calibration | Semantic thresholds derived from labeled cohorts, not arbitrary defaults. |
| Observability | Coverage, unresolved bindings, grader disagreements and drift are monitored. |

---

## 14. Open questions and decisions required

| Decision area | Open question | Recommended direction |
|---|---|---|
| Ontology scope | Will the ontology include only business/domain concepts, or also agent/state/policy/evaluation concepts? | Recommend all five layers so the ontology is actually executable for agent evaluation. |
| Ontology ownership | Who approves concepts and rule mappings: engineering, business, risk, policy owners, or a joint governance group? | Recommend joint ownership with explicit technical and policy approvers. |
| Authoritative truth precedence | If policy text, system configuration, operational DB and SME guidance disagree, which wins? | Define precedence and represent conflicts; never silently reconcile. |
| Trace metadata | Can production agents emit state, step, tool args/results, memory events and terminal status? | This is the single biggest determinant of reverse-GT complexity. |
| Workflow flexibility | Which agents have a prescribed order versus multiple valid plans? | Support strict-order and constraint/milestone modes. |
| Semantic judge boundary | Which properties are allowed to use an LLM/model judge? | Only interpretation relative to policy-derived truth; never the sole source of normative truth. |
| Human review threshold | Which low-confidence or high-severity cases require adjudication? | Define by risk/materiality and binding/judge confidence. |
| Policy extraction approval | Can low-risk rules auto-publish, or must every extracted rule be approved? | Tier by rule materiality and extraction confidence. |
| GMS target problem | Which observed gaps require GMS-like geometry? | Measure first: entity binding, claim grounding, contradiction, path consistency, calibration. |
| Evaluation roll-up | Do stakeholders need a single score? | Keep dimensions separate; define hard gates/roll-up only for decision-specific reporting. |
| World-state integration | Will evaluator access authoritative backend state during tests/replay? | Needed for strong outcome verification in action-taking agents. |
| Production use | Is trace evaluation offline replay only or near-real-time monitoring? | Architecture can support both; latency/privacy requirements differ. |
| Multi-agent scope | How are delegation, hand-offs and shared memory represented? | Add agent identity, delegation edges and inter-agent milestones when needed. |
| Policy change SLA | How quickly must ontology/rules/tests update after policy change? | Drive incremental recompilation and impact analysis requirements. |
| Validation set | What labeled cohort will validate the GT compiler and semantic oracle? | Must exist before calibrated semantic verdicts are trusted. |

---

## 15. Phased implementation roadmap

| Phase | Scope | Exit artifact |
|---|---|---|
| Phase 0 — Architecture alignment | Freeze terminology, ontology scope, GT contract schema, assertion taxonomy, trace envelope and versioning model. Select one narrow use case as reference implementation. | Signed architecture decision record; schema prototypes; trace contract. |
| Phase 1 — Executable ontology | Merge Scenario Generator concepts with eval-poc policy/state/rule concepts. Structure transition predicates. Add exact value/provenance store. | Versioned ontology + rule DSL + validators. |
| Phase 2 — Unified GroundTruthResolver | Generalize `GroundTruthExtractor` into scenario and trace entry points returning one `EvaluationContract`. | `resolve_for_scenario` + `resolve_for_trace`; deterministic binding for metadata-rich traces. |
| Phase 3 — Deterministic holistic evaluator | Implement state/tool/transition/sequence/count/terminal/governance graders and assertion-level explanations. | End-to-end deterministic evaluation report. |
| Phase 4 — Scenario Generator integration | Compile every generated base scenario into a contract; add ontology coverage metrics and risk-based allocation. | Scenario pack + contracts + coverage report. |
| Phase 5 — Enrichment and resilience | Add GT-invariant factors, covering-array/risk-weighted sampling and tool/state fault injection. | Robustness/resilience campaign engine. |
| Phase 6 — Semantic oracle V1 | Aliases + embeddings/reranker + constrained LLM/NLI claim judge + confidence + adjudication. | Semantic response/claim evaluation with validation cohort. |
| Phase 7 — Statistical diagnosis | Repeated trials, factor attribution, weak-link/component attribution and trend reporting. | Diagnostic analytics and regression dashboards. |
| Phase 8 — GMS-like R&D | Prototype calibrated relation scoring, contradiction representation and path consistency only where V1 gaps justify it. | Evidence-based decision on full GMS-equivalent investment. |

---

## 16. Example end-to-end flows

### 16.1 Synthetic scenario flow

```
Policy: maximum three authentication attempts; after third failure transfer and stop servicing.

Ontology/rules
  MAX_AUTH_ATTEMPTS <= 3
  FAILED && attempts < 3 -> RETRY
  FAILED && attempts == 3 -> MAX_RETRY -> TRANSFER
  TRANSFER -> terminal
  servicing after transfer -> prohibited

Scenario Generator
  initial: authenticated=false, attempts=2
  event: third authentication attempt returns FAILED
  perturbation: frustrated user + ASR noise

EvaluationContract
  required: failure communication, max-retry behavior, transfer
  forbidden: fourth auth attempt, servicing
  terminal: transferred=true

Agent trace
  auth attempt 3 -> FAILED
  agent asks user to try again

Evaluation
  CountAssertion: FAIL (would create attempt 4)
  TransitionAssertion: FAIL (expected max_retry/transfer)
  TerminalAssertion: FAIL
  Communication semantic quality: potentially PASS in isolation

Diagnosis
  first violated assertion: MAX_AUTH_ATTEMPTS
  component: planner/state logic
  source: policy rule + evidence span
```

### 16.2 Trace-first replay flow

```
Observed trace
  state metadata: authentication
  attempt_count: 2
  tool_result: FAILED
  agent response: "I will transfer you now."

StateBinder
  authentication_retry, confidence=1.0 (metadata-rich)

GroundTruthResolver
  applicable rule: FAILED && attempts < 3 -> RETRY
  contract: communicate failure + request another attempt

Evaluator
  tool/state checks: deterministic
  response semantics: semantic judge against required_behavior
  verdict: premature transfer / policy violation

No pre-generated scenario was required.
```

### 16.3 Flexible planning flow

```
Goal: complete an eligible servicing request.

Contract
  must verify identity before disclosure
  must retrieve governing policy before commitment
  must reach approved terminal state
  may clarify user intent before or after policy retrieval
  must not call restricted tool before authorization

Agent A path: clarify -> verify -> retrieve -> act
Agent B path: verify -> clarify -> retrieve -> act

Both may pass because the contract encodes dependencies and milestones,
not an arbitrary single canonical sequence.
```

---

## 17. Key risks and mitigations

| Risk | Consequence | Mitigation |
|---|---|---|
| Ontology becomes a giant hand-maintained graph | High maintenance; slow onboarding. | Separate stable upper ontology from domain instances; automate extraction but require evidence/approval. |
| LLM extraction errors become "truth" | Systematic false evaluation. | Evidence checks, typed validation, approval tiers, conflict states and regression tests. |
| RuleCompiler remains domain-specific Python | Every use case forks code. | Generic assertion primitives + declarative DSL + plugin functions only for exceptional logic. |
| Exact path matching rejects valid agents | False failures and discourages agent flexibility. | Milestone/dependency/terminal-state evaluation; strict order only when policy requires it. |
| LLM judge becomes hidden oracle | Non-reproducible, circular truth. | Contract-first judging; deterministic graders first; calibration/adjudication. |
| Production trace lacks state metadata | Reverse GT becomes inference-heavy. | Define trace instrumentation requirement early; StateBinder with confidence as fallback. |
| GMS R&D dominates roadmap | Core value delayed by proprietary/complex machinery. | SemanticOracle interface; staged GMS-lite; require measured gap before advanced geometry. |
| Coverage claims are vague | Cannot defend "comprehensive". | Ontology-based coverage metrics and explicit uncovered items. |
| Policy changes invalidate tests silently | Stale GT. | Version linkage, impact analysis, contract regeneration and targeted regression. |
| One aggregate score hides material failures | Poor risk decisions. | Dimension-level metrics, hard policy gates and assertion-level explanations. |

---

## 18. Recommended target state and conclusions

The recommended target is not a GMS clone and not a standalone scenario generator. It is a
policy-to-evaluation compiler centered on a versioned executable ontology. The Scenario Generator
becomes the test-space compiler; the eval-poc `GroundTruthExtractor` becomes the seed for a
generalized `GroundTruthResolver`; the book contributes controlled enrichment, experimental design,
multi-level evaluation and semantic-oracle concepts; external benchmarks contribute
state/outcome/milestone evaluation patterns.

> **Recommended architectural commitment:** Commit now to the ontology + executable specification +
> `EvaluationContract` + dual-entry `GroundTruthResolver`. Keep the semantic oracle replaceable.
> This gives immediate value with deterministic policy/state evaluation and preserves a clean path
> to GMS-like capabilities if later evidence shows they are needed.

### 18.1 What should be built first

1. Define the five-layer ontology and stable IDs.
2. Define structured transition/rule predicates and generic assertion primitives.
3. Define the `EvaluationContract` schema.
4. Generalize GT extraction to scenario and trace entry points.
5. Instrument the agent trace envelope so state/tool metadata is available.
6. Implement deterministic graders and assertion-level explanations.
7. Integrate Scenario Generator output with the contract engine.
8. Only then add semantic judging, controlled enrichment, fault injection and advanced
   semantic-oracle R&D.

### 18.2 What should not be a prerequisite

- Full geometric memory implementation.
- An LLM judge for deterministic facts.
- A perfect automatic policy extractor.
- One universal aggregate agent score.
- One canonical trajectory for all agent architectures.
- Full-factorial enumeration of every perturbation combination.

---

## Appendix A — Proposed EvaluationContract schema

```
EvaluationContract:
  contract_id: str
  policy_version: str
  ontology_version: str
  evaluator_version: str
  subject:
    scenario_id: optional[str]
    trace_id: optional[str]
  binding:
    state_id: str
    confidence: float
    alternatives: list[BindingCandidate]
  initial_state: dict[str, typed_value]
  required_actions: list[ActionExpectation]
  allowed_actions: list[ActionExpectation]
  forbidden_actions: list[ActionExpectation]
  milestones: list[Milestone]
  transitions: list[TransitionExpectation]
  terminal_conditions: list[Predicate]
  assertions: list[Assertion]
  provenance: list[EvidenceRef]
  derivation:
    gt_level: L0..L5
    resolver_version: str
    semantic_oracle_version: optional[str]
```

## Appendix B — Proposed assertion schema

```
Assertion:
  assertion_id: str
  type: enum
  scope: turn | event | state | trajectory | outcome
  predicate: structured expression
  expected: typed value / bool / set / range
  severity: info | warning | error | blocker
  grader: deterministic | semantic | hybrid | human
  source_rule_ids: list[str]
  evidence_refs: list[str]
  derivation_level: L0..L5
  confidence: optional[float]
  status: pass | fail | uncertain | not_applicable
  explanation: str
```

## Appendix C — Strategy comparison matrix

| Approach | Primary strength | Primary limitation | Recommended role |
|---|---|---|---|
| Scenario Generator | Systematic ontology/graph-based scenario-space construction and practical capability scoping. | GT contract and runtime trace evaluation are not yet rich enough. | Primary test-space compiler. |
| Procedural KG eval-poc | Executable workflow/rule GT with occurrence-level state and assertions. | Domain-specific rule compiler; scenario-first maturity; semantic binding unresolved. | Seed for executable specification and GroundTruthResolver. |
| KnowlytiX/GMS methodology | Correct-by-construction oracle concept, enrichment, semantic verification, designed experiments, attribution. | Advanced/proprietary implementation complexity. | Methodological source; optional semantic-oracle target. |
| τ-bench | Outcome verification against stateful environment; reliability over repeated trials. | Benchmark-specific environment authoring cost. | World-state/outcome verification pattern. |
| ToolSandbox | State dependencies and milestone evaluation over arbitrary trajectories. | Benchmark/tool-domain framing. | Milestone and flexible-trajectory evaluation pattern. |
| Ragas | KG-driven synthetic test generation with query/persona variation. | Primarily RAG/query generation, not procedural policy compliance. | Synthetic realization/enrichment reference. |
| Anthropic guidance | Practical grader taxonomy and transcript/outcome framing. | Guidance, not a policy-GT implementation. | Evaluation harness and grader design principles. |

## Appendix D — Source map and research references

**User-provided sources**

- `Beyond-Ship-and-Pray.md` — KnowlytiX methodology: graph/exact memory, GMS primitives, GEODE
  oracle, base taxonomy, enrichment, designed experiments, agentic evaluation, failure attribution
  and resilience.
- `WHOLE_STRATEGY_BRIEF_FOR_AI.md` — detailed handover contrasting the book with the Card
  Authentication procedural-KG POC and proposing reverse ground-truth resolution.
- `scene_generator_latest.zip` — Scenario Generator implementation reviewed for
  Capability/Decision/State/Tool/Scenario/TurnMeta structures, DecisionGraph capability spans,
  coverage/probes/materiality/grounding patterns.
- `eval-poc-1(3).zip` — procedural-KG evaluation implementation reviewed for
  `GroundTruthExtractor`, `TurnGroundTruth`, assertions, path resolution, state-before/state-after
  and versioned GT.

**External references**

- Yao et al., "τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains,"
  arXiv:2406.12045. https://arxiv.org/abs/2406.12045
- Lu et al., "ToolSandbox: A Stateful, Conversational, Interactive Evaluation Benchmark for LLM
  Tool Use Capabilities," Findings of NAACL 2025.
  https://aclanthology.org/2025.findings-naacl.65/
- Anthropic, "Demystifying evals for AI agents," Jan. 9, 2026.
  https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Ragas documentation, "Testset Generation for RAG."
  https://docs.ragas.io/en/stable/concepts/test_data_generation/rag/

## Appendix E — Immediate architecture workshop agenda

1. Confirm ontology scope and ownership.
2. Approve `EvaluationContract` and assertion taxonomy.
3. Inventory available runtime trace fields and gaps.
4. Classify one reference use case into domain/agent/state/policy/evaluation ontology layers.
5. Convert 10–20 policy rules into the proposed rule DSL and assertion primitives.
6. Run the same rules through two flows: generated scenario and observed trace.
7. Define deterministic grader coverage and identify residual semantic-only checks.
8. Create a labeled semantic validation cohort before selecting a GMS-lite implementation.
9. Agree coverage metrics and materiality-based test allocation.
10. Document go/no-go criteria for advanced GMS-like R&D.
