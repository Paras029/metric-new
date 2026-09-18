# eval-poc — Curated AI-Readable Codebase

> **Source:** Provided as context — a deliberately reduced representation of the `eval-poc`
> repository (Card Authentication Voice Bot procedural-KG evaluation POC).
> **Status in this repo:** grounding document. This is the reference implementation of the
> executable-oracle pattern (`GroundTruthExtractor` → `GroundTruth` → `TurnGroundTruth` →
> `GroundTruthAssertion`) that the Scenario Generator is being generalized toward.

It keeps the core implementation, policy/ontology definitions, KG schema/data needed to understand
the architecture, two governing documents, the simulator, and four representative scenario
artifacts. It omits bulk generated scenario archives, duplicate JSON/YAML copies, notebooks, caches,
package metadata, SQLite databases, generated HTML, `.env` secrets, and empty/boilerplate package
initializers.

## Curated contents

- `pyproject.toml`
- `configs/base.yaml`, `configs/card_authentication.yaml`, `configs/thresholds.yaml`
- `catalogs/card_authentication/{base_catalog,customer_utterances,factor_catalog}.yaml`
- `document/Card_Authentication_Voice_Bot_POC_Operating_Procedure_with_Flowchart.md`
- `document/Card_Authentication_Voicebot_Testing_Framework_Implementation_Blueprint.md`
- `knowledge_graph/` — `.env.example`, `03_validation_queries.cypher`, `connection.py`, `ingest.py`,
  `data/{00_schema,01_constraints,02_card_authentication_graph}.cypher`
- `simulator/card_authentication_simulator.py`
- `data/customers/seed_customers.py`
- `data/scenarios/base/` — `PATH_COVERAGE_AC.yaml`, `DECISION_BOUNDARY_FC_FC_AC.yaml`,
  `SCOPE_ESCALATION_AC.yaml`; `data/scenarios/enriched/PATH_COVERAGE_AC__E001.yaml`
- `src/voicebot_eval/` — `catalogs/`, `cli/`, `oracle/`, `scenarios/`, `schemas/`

## Intentionally omitted

- `data/archive/**` and the large generated `data/scenarios/**` corpus except four representative
  YAML examples.
- Duplicate JSON scenario representations where the YAML version is sufficient.
- All Jupyter notebooks (logic is represented by the underlying Python modules).
- `Beyond-Ship-and-Pray.md` (tracked separately).
- `.env`, SQLite customer DB, generated graph HTML, `__pycache__`, `*.egg-info`.

---

# Part 1 — Project configuration

## `pyproject.toml`

```toml
[project]
name = "voicebot-eval"
version = "0.1.0"
description = "Evaluation/validation framework for the Card Authentication Voice Bot POC"
requires-python = ">=3.10"
dependencies = [
    "neo4j>=5.0",
    "python-dotenv>=1.0",
    "pydantic>=2.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=7.0"]
llm = ["openai>=1.0"]

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

## `configs/base.yaml`

```yaml
# Shared defaults for all voicebot-eval configs.
neo4j:
  uri_env: NEO4J_URI
  user_env: NEO4J_USER
  password_env: NEO4J_PASSWORD
  database_env: NEO4J_DATABASE

oracle:
  oracle_version: poc-1
```

## `configs/card_authentication.yaml`

```yaml
# Card Authentication Voice Bot POC configuration.
extends: base.yaml

voicebot_id: card_authentication

catalogs:
  base_catalog: catalogs/card_authentication/base_catalog.yaml
  factor_catalog: catalogs/card_authentication/factor_catalog.yaml
  customer_utterances: catalogs/card_authentication/customer_utterances.yaml
  customers_database: data/customers/customers.sqlite

data:
  scenarios_dir: data/scenarios
  runs_dir: data/runs
  reports_dir: data/reports

max_authentication_attempts: 3
```

## `configs/thresholds.yaml`

```yaml
# Calibration thresholds. Empty for this POC: all workflow assertions are
# deterministic and do not depend on a probabilistic score threshold (see
# blueprint section 19).
thresholds: {}
```

---

# Part 2 — Catalogs

## `catalogs/card_authentication/base_catalog.yaml`

```yaml
version: 1
voicebot_id: card_authentication
# Every family produces complete opening-to-terminal journeys, the unit the
# agent simulator executes and the evaluator grades.
families:
  - id: path_coverage
    name: Path Coverage
    purpose: Cover every legal end-to-end journey path discovered from the knowledge graph.
  - id: decision_boundary
    name: Decision Boundary
    purpose: Exercise authentication attempt-count boundaries and terminal branching.
  - id: scope_escalation
    name: Scope and Escalation
    purpose: Check no servicing occurs and transfer follows legal terminal branches.
```

## `catalogs/card_authentication/customer_utterances.yaml`

```yaml
version: 1
voicebot_id: card_authentication
utterances:
  - id: AUTH_CLEAR_001
    semantic_outcome: CLEAR
    text: "My customer ID is {customer_id} and my authentication code is {authentication_code}."
    tags: [canonical, concise]
  - id: AUTH_CLEAR_002
    semantic_outcome: CLEAR
    text: "Sure, my customer ID is {customer_id}; the authentication code is {authentication_code}."
    tags: [alternate, conversational]
  - id: AUTH_UNCLEAR_001
    semantic_outcome: UNCLEAR
    text: "Um, I think my customer ID is {customer_id}, but I am not sure about the authentication code."
    tags: [unclear, hesitant]
```

## `catalogs/card_authentication/factor_catalog.yaml`

```yaml
version: 1
voicebot_id: card_authentication
factors:
  - id: customer_record
    name: Customer Record
    levels: [customer_001, customer_002, customer_003]
    identity_levels: []
    applies_to: [CUSTOMER]
    invariant: true
  - id: paraphrase
    name: Paraphrase
    levels: [canonical, alternate]
    identity_levels: [canonical]
    applies_to: [CUSTOMER]
    invariant: true
  - id: disfluency
    name: Disfluency
    levels: [clean, hesitant]
    identity_levels: [clean]
    applies_to: [CUSTOMER]
    invariant: true
  - id: verbosity
    name: Verbosity
    levels: [concise, verbose]
    identity_levels: [concise]
    applies_to: [CUSTOMER]
    invariant: true
  - id: register
    name: Register
    levels: [neutral, formal]
    identity_levels: [neutral]
    applies_to: [CUSTOMER]
    invariant: true
  - id: affect
    name: Affect
    levels: [neutral, anxious]
    identity_levels: [neutral]
    applies_to: [CUSTOMER]
    invariant: true
```

---

# Part 3 — Governing documents

## Card Authentication Voice Bot — Fictional POC Operating Procedure

### 1. Purpose and journey objective

A deliberately simple voice-bot journey for customer authentication. The bot welcomes the customer,
authenticates the customer, allows a maximum of three authentication attempts, communicates the
authentication outcome, and then transfers the call to CCP for further servicing. The bot does not
perform any additional servicing itself.

### 2. POC scope

- Welcome the customer and state the purpose of the interaction.
- Authenticate the customer.
- Allow a maximum of 3 authentication retries/attempts.
- On successful authentication, inform the customer and transfer to CCP.
- After authentication remains unsuccessful at the maximum retry limit, inform the customer that
  authentication could not be completed and transfer to CCP.
- CCP handles all further servicing after transfer.

### 3. Operating procedure

**A. Opening and authentication.** Play the required opening statement. Explain that authentication
is needed before account-specific servicing can be discussed. Call `authenticate_customer`. Continue
only according to the authentication result.

**B. Authentication attempts.** Request the information required for authentication and call
`authenticate_customer`. Maintain an authentication attempt counter. The bot must not perform any
other servicing activity.

**C. Successful authentication.** If `authenticate_customer` returns `AUTHENTICATED`, inform the
customer that they have been successfully authenticated. Then transfer the call to CCP.

**D. Failed authentication and retry.** If authentication fails, inform the customer that the
authentication was unsuccessful and ask them to try again. The bot may make up to 3 total
authentication attempts. It must not make a fourth attempt.

**E. Maximum retry reached.** If authentication remains unsuccessful after the third attempt, inform
the customer that authentication could not be completed and that the call will be transferred to CCP
for further assistance. Then transfer the call to CCP.

**F. Transfer and end of automated journey.** After successful authentication or after the maximum
retry limit is reached, call `transfer_to_ccp`. The automated journey ends once the transfer is
initiated.

### 4. Voice and agentic behavior rules

- **Conversation state:** Remember the authentication attempt count and authentication result for
  the duration of the interaction.
- **Retry control:** Enforce a hard maximum of 3 authentication attempts. The retry counter must not
  reset during the same call.
- **Do not guess:** If required authentication information is unclear or cannot be understood, treat
  the attempt as unsuccessful and apply the retry logic.
- **Grounded outcome:** Only tell the customer that authentication succeeded when
  `authenticate_customer` returns `AUTHENTICATED`.
- **Failure messaging:** After the third unsuccessful attempt, clearly inform the customer that
  authentication could not be completed before transferring the call.
- **No servicing:** Do not answer or execute additional account-specific servicing requests in this
  POC. CCP owns further servicing.
- **Transfer:** Transfer to CCP after authentication success or after the third unsuccessful attempt.

### 5. Illustrative tools / APIs

| Tool / API | When used | Example output | Required bot behavior |
|---|---|---|---|
| `authenticate_customer` | For each authentication attempt | `AUTHENTICATED` / `FAILED` | `AUTHENTICATED` → success message → transfer to CCP. `FAILED` → failure message and retry until the third attempt. |
| `transfer_to_ccp` | After authentication success or max retry | `TRANSFERRED` / `FAILED` | End automated servicing after transfer is initiated. Handle a transfer failure using the platform's defined fallback. |

### 6. Required vs. generated language

- **Opening:** "Welcome. For your security, I need to authenticate you before we proceed."
- **Successful authentication:** "Thank you. You have been successfully authenticated. I will now
  connect you to CCP for further servicing."
- **Retry:** "I'm sorry, I couldn't verify your details. Please try again."
- **Maximum retry / failure:** "I'm sorry, I'm unable to authenticate you at this time. I will now
  connect you to a representative for further assistance."
- **Generated/conversational language:** The bot may vary wording naturally for prompts and
  transitions, provided the meaning remains consistent with the operating procedure.

### 7. Evaluation-critical behaviors

- Welcomes the customer before attempting authentication.
- Calls the authentication process and tracks attempts correctly.
- Never exceeds 3 authentication attempts in one interaction.
- Communicates successful authentication before transferring the call.
- Communicates authentication failure/max retry before transferring the call.
- Transfers to CCP after either authentication success or the maximum retry limit.
- Does not perform additional servicing within the POC.

### 9. POC design boundary

This is intentionally a minimal authentication-and-transfer POC. There is no card replacement
workflow, knowledge retrieval, order placement, delivery selection, transaction review, or other
servicing logic inside the bot. The only automated outcomes are successful authentication followed
by transfer to CCP, or unsuccessful authentication after 3 attempts followed by transfer to CCP.

---

## Card Authentication Voicebot Testing Framework — Implementation Blueprint

| Document property | Value |
|---|---|
| Purpose | Build a complete, but deliberately small, evaluation/validation package for the Card Authentication Voice Bot POC. |
| Methodology | *Beyond "Ship and Pray"* — authoritative ground truth, base scenarios, ground-truth-invariant enrichment, designed experiments, trajectory testing and resilience. |
| POC scope | Welcome → authenticate (max 3 attempts) → success/retry/max-retry → transfer to CCP. No additional servicing in the bot. |
| Implementation style | Modular Python package with a Neo4j-backed procedural graph oracle, scenario generator, deterministic graders and optional HF/PyTorch components. |

### 1. Executive design decision

Treat the card-authentication bot as a small governed, stateful agent rather than a single
answer-generating model. Preserve the enterprise methodology: authoritative ground truth, base cases,
ground-truth-invariant enrichment, component testing, system testing, trajectory/process testing,
resilience testing and failure attribution.

For this POC, the oracle can be implemented almost entirely from the procedural knowledge graph. No
exact transaction store, temporal oracle, entity-resolution store, confirmation oracle, or
charge-action policy engine is required. The central design is:

```
Voicebot KG
   ↓
Procedural Graph Reader
   ↓
Scenario + runtime context
   ↓
GroundTruthExtractor
   ↓
Expected trajectory + atomic assertions
   ↓
SUT trajectory
   ↓
Deterministic evaluation
```

**Design principles**

- Ground truth is authoritative, replayable, versioned and independent of the system under test.
- The observation unit is the complete trajectory: customer input/transcript, bot response, tool
  calls, tool results, state/step, transfer and terminal status.
- The graph defines procedure and rules; the scenario selects the runtime conditions; the extractor
  instantiates the rules for that scenario.
- Deterministic graph/rule checks take priority over generic LLM judging for workflow, tool,
  attempt-count, transfer and policy assertions.
- Voice evaluation separates intended customer input, materialized audio, ASR transcript and agent
  behavior so failures can be localized.
- Every enrichment factor must be ground-truth invariant. A factor that changes the correct
  authentication outcome belongs in the base scenario, not the enrichment catalog.
- Production failures become regression scenarios and are linked back to the graph rule or scenario
  factor that exposed them.

### 2. Framework layers

| Layer | Primary responsibility | POC implementation |
|---|---|---|
| Oracle | Determine expected steps, turns, outcomes, tool calls, rules and terminal behavior. | Neo4j graph + deterministic extractor + runtime context + provenance. |
| Catalogs | Define base cases and presentation factors. | YAML/JSON under `catalogs/card_authentication/`. |
| DOE | Choose statistically useful test subset. | Start with crossed design; Sobol+refine optional. |
| Materializer | Turn scenario assignments into customer inputs/text/audio. | Deterministic templates first; HF/TTS/ASR later. |
| SUT adapter | Normalize bot telemetry without deciding correctness. | Pydantic `SUTRun` + adapter API. |
| Evaluator | Grade component, outcome, trajectory and resilience. | Mostly deterministic POC graders. |
| Attribution | Identify factor or first-failing component. | Empirical rates first; logistic/weak-link when sample size supports. |
| Monitoring | Turn production failures into regression cases. | Metrics + scenario mining + release gates. |

### 4. Core data model and contracts

```python
class Scenario(BaseModel):
    scenario_id: str
    base_id: str
    voicebot_id: str
    factors: dict[str, str] = {}
    authentication_attempts: list["AuthenticationAttempt"]
    input_mode: Literal["text", "audio", "mixed"] = "text"
    oracle_ref: str
    metadata: dict[str, Any] = {}

class AuthenticationAttempt(BaseModel):
    attempt_number: int
    customer_input: str
    interpreted_outcome: Literal["CLEAR", "UNCLEAR"]
    tool_outcome: Literal["AUTHENTICATED", "FAILED"]

class GroundTruthAssertion(BaseModel):
    assertion_id: str
    category: str
    predicate: str
    expected: bool
    severity: Literal["ERROR", "WARNING"] = "ERROR"
    source_rule_id: str | None = None
    source_step_id: str | None = None
    source_turn_id: str | None = None
    expected_value: Any = None

class GroundTruth(BaseModel):
    scenario_id: str
    voicebot_id: str
    expected_steps: list[str]
    expected_tool_calls: list[dict[str, Any]]
    expected_turns: list[dict[str, Any]]
    expected_outcomes: list[str]
    assertions: list[GroundTruthAssertion]
    oracle_version: str

class TrajectoryEvent(BaseModel):
    ts: datetime
    turn_id: int
    step_id: str | None
    actor: Literal["BOT", "CUSTOMER", "SYSTEM"]
    event_type: str
    transcript: str | None
    tool_name: str | None
    tool_args: dict[str, Any] | None
    tool_result: dict[str, Any] | None
    state_before: dict[str, Any]
    state_after: dict[str, Any]
    latency_ms: float | None

class SUTRun(BaseModel):
    run_id: str
    scenario_id: str
    sut_version: str
    asr_version: str | None
    tts_version: str | None
    events: list[TrajectoryEvent]
    terminal_state: str
    transfer_result: str | None
    artifacts: dict[str, str]
```

### 5. GroundTruthOracle architecture

```python
class GroundTruthOracle(Protocol):
    def get_start_step(self, voicebot_id: str) -> dict: ...
    def get_step(self, step_id: str) -> dict: ...
    def get_next_steps(self, step_id: str) -> list[dict]: ...
    def get_step_turns(self, step_id: str) -> list[dict]: ...
    def get_step_rules(self, step_id: str) -> list[dict]: ...
    def get_tool_outcomes(self, tool_id: str) -> list[dict]: ...
    def resolve_scenario_path(self, scenario: Scenario) -> list[str]: ...
    def extract_ground_truth(self, scenario: Scenario) -> GroundTruth: ...
    def validate_ground_truth(self, ground_truth: GroundTruth) -> None: ...
```

The resolver maintains runtime context such as `attempt_count` and `last_tool_outcome`. The graph
stores the rule "maximum three attempts"; the resolver determines when that rule is reached for the
current scenario.

**Rule → assertion mapping (blueprint table)**

| KG rule | Compiled assertion | Evaluation evidence |
|---|---|---|
| `OPENING_BEFORE_AUTH` | `opening_before_authentication` | trajectory order of steps/events |
| `AUTHENTICATION_REQUIRED` | `authentication_tool_called` | `authenticate_customer` tool event |
| `MAX_THREE_ATTEMPTS` | `attempt_count <= 3` | number of authentication calls |
| `ATTEMPT_COUNTER_PERSISTS` | attempt number is monotonic | runtime attempt indices |
| `UNCLEAR_IS_FAILURE` | `UNCLEAR` implies `FAILED` branch | customer interpretation + next step |
| `SUCCESS_REQUIRES_AUTHENTICATED` | success message requires `AUTHENTICATED` | tool result immediately before success |
| `FAILURE_MESSAGE_BEFORE_RETRY` | failure message precedes retry | trajectory ordering |
| `MAX_RETRY_MESSAGE_BEFORE_TRANSFER` | max-retry message precedes transfer | trajectory ordering |
| `NO_ADDITIONAL_SERVICING` | no servicing step/tool after auth path | step/tool set |
| `TRANSFER_AFTER_SUCCESS` | success path transfers | trajectory order |
| `TRANSFER_AFTER_MAX_RETRY` | third failure path transfers | trajectory order |
| `END_ON_TRANSFER` | journey terminates after transfer initiated | terminal state/transfer event |

### 6. Graph schema

```
(:Voicebot)-[:HAS_STEP]->(:Step)
(:Voicebot)-[:STARTS_WITH]->(:Step)
(:Step)-[:NEXT {when: ...}]->(:Step)
(:Step)-[:HAS_TURN]->(:Turn)
(:Step)-[:USES_TOOL]->(:Tool)
(:Step)-[:GOVERNED_BY]->(:Rule)
(:Turn)-[:EXPECTS_OUTCOME]->(:Outcome)
(:Turn)-[:GOVERNED_BY]->(:Rule)
(:Tool)-[:RETURNS]->(:Outcome)
```

| Node | Purpose in POC | Important properties |
|---|---|---|
| Voicebot | Root of one procedural bot definition | id, name, version, source_document |
| Step | Procedural phase; not a conversational turn | id, name, terminal, description |
| Turn | Bot/customer conversational event inside a step | id, actor, turn_type, canonical_text, required, generated_allowed |
| Tool | External operation | id, name, input_schema, output_schema, success_condition, failure_behavior |
| Outcome | Branching result | id, code, description |
| Rule | Constraint / requirement / invariant | code, statement, rule_type, subject, predicate, object, polarity |

**Graph validation (minimum):** exactly one `STARTS_WITH` step; every non-terminal step has at least
one `NEXT` path; every referenced tool and outcome exists; every critical rule is connected to a
step/turn; transfer is terminal; no graph path can silently bypass the three-attempt limit or
required messages.

### 7. Base taxonomy

| Family | Base category | POC example | Ground truth |
|---|---|---|---|
| Conversation understanding | Authentication input clarity | clear vs unclear authentication information | Turn + `UNCLEAR_IS_FAILURE` |
| Workflow | Opening gate | welcome before authentication | Rule + trajectory |
| Workflow | Attempt count | one, two or three attempts | Runtime context + `MAX_THREE_ATTEMPTS` |
| Tool | Authentication result | `AUTHENTICATED` / `FAILED` | Tool outcome |
| Workflow | Retry branching | failure under three attempts | `NEXT` condition |
| Workflow | Max retry branching | third failure | `NEXT` condition |
| Response | Required message | success / retry / max-retry language | Turn + rule |
| Escalation | CCP transfer | transfer after success or third failure | Tool + trajectory |
| Scope | No additional servicing | no downstream servicing | `NO_ADDITIONAL_SERVICING` |
| Termination | End on transfer | journey ends after transfer initiated | `END_ON_TRANSFER` |

**Seed-case minimum:** successful first attempt; failed then successful second attempt; three
consecutive failures; unclear then successful; transfer-tool failure.

### 8. Enrichment catalog and voice-specific factors

| Group | Examples | Priority | GT invariant? |
|---|---|---|---|
| Query clarity | clear, concise, verbose, hesitant | P0 | Yes |
| Paraphrase | semantically equivalent wording | P0 | Yes |
| Disfluency | fillers, repetition, self-correction | P1 | Yes |
| Speech rate | slow, normal, fast | P1 | Yes |
| Background noise | none, moderate | P1 | Yes |
| ASR robustness | minor transcript corruption preserving meaning | P1 | Yes |
| Silence / non-response | short silence within supported timeout | P1 | Scenario-specific |
| Emotion | neutral, frustrated, anxious | P2 | Yes |

> Do not combine several factors into an opaque "hard voice case". Keep factors orthogonal so later
> attribution can identify whether failures are driven by clarity, ASR, noise or another factor.

### 9. Canonical base scenarios

| Scenario ID | Authentication outcomes | Expected path |
|---|---|---|
| `AUTH_SUCCESS_001` | `AUTHENTICATED` | opening → authentication → success → transfer |
| `AUTH_RETRY_SUCCESS_001` | `FAILED`, `AUTHENTICATED` | opening → authentication → retry → authentication → success → transfer |
| `AUTH_MAX_RETRY_001` | `FAILED` ×3 | opening → authentication → retry → authentication → retry → authentication → max_retry → transfer |
| `AUTH_UNCLEAR_001` | `UNCLEAR`, `AUTHENTICATED` | UNCLEAR treated as FAILED → retry → authentication → success → transfer |
| `AUTH_TRANSFER_FAIL_001` | `AUTHENTICATED` + transfer failure | success message → transfer attempt → platform fallback |

**Materialization pipeline**

```
semantic scenario → text materializer → conversation materializer
   ├→ perfect transcript
   └→ TTS/audio → audio perturbation → ASR → actual transcript → VOICEBOT
```

Persist semantic input, intended text, audio artifact hash and actual ASR transcript so an agent
defect can be distinguished from an audio/ASR defect.

### 12. SUT adapter — required telemetry fields

- `scenario_id`, `run_id`, SUT version, prompt/config version
- customer transcript and ASR transcript if applicable
- current procedural step if exposed
- every `authenticate_customer` call, arguments, result, latency and retry count
- the bot response before and after each authentication outcome
- every `transfer_to_ccp` call and result
- final response, terminal state and transfer status
- correlation IDs and provenance references

> The adapter translates telemetry; it does not infer correctness. The evaluator compares telemetry
> to the already-extracted ground truth.

### 13–15. Evaluation levels

**Component metrics**

| Component | Primary metric | POC diagnostic |
|---|---|---|
| ASR | Semantic/entity accuracy | authentication information corruption |
| Conversation understanding | Correct clear/unclear interpretation | UNCLEAR incorrectly treated as success |
| State manager | Transition accuracy | skipped/repeated authentication steps |
| Tool orchestration | Correct tool + outcome handling | missing/wrong `authenticate_customer` call |
| Response grounding | Claim consistency | success claimed without `AUTHENTICATED` |
| Escalation/transfer | Correct transfer decision | missing / premature / repeated transfer |
| Operational workflow | Trajectory adherence | opening/order/retry/max-retry violations |

**Weak-link rule:** for an end-to-end failure, identify the first graded component in execution order
that deviated from ground truth. Keep component defect and overall outcome separate.

**System outcome**

```python
SystemPass = all([
    opening_correct,
    authentication_calls_correct,
    attempt_bound_respected,
    branch_correct,
    required_message_correct,
    transfer_decision_correct,
    no_servicing_violation,
    terminal_state_correct,
])
```

**Operational properties**

| Property | Requirement | Scoring |
|---|---|---|
| Opening gate | Opening before authentication | Deterministic trajectory check |
| Authentication attempt | Call auth API with customer response | Tool trajectory |
| Retry bound | Retry after failure; max three attempts | Attempt counter |
| Unclear input | Treat unclear info as unsuccessful | Outcome + next step |
| Success grounding | Say success only after `AUTHENTICATED` | Tool result → response claim |
| Max-retry handling | State inability before transfer | Order check |
| No servicing | No account-specific servicing | Prohibited action/tool check |
| Escalation | Transfer after success or third failure | Tool + workflow |
| Termination | End journey when transfer initiated | Terminal-state check |

### 16. Resilience and fault injection

```python
class FaultProfile(BaseModel):
    tool_pattern: str
    kind: Literal["hard_error", "timeout", "malformed", "plausible_wrong", "duplicate"]
    probability: float = 1.0
    payload_override: dict[str, Any] | None = None
    latency_ms: int | None = None

class ToolGateway:
    def invoke(self, tool_name, args, real_executor):
        profile = self.active_profile(tool_name)
        return self.apply_fault(profile, tool_name, args, real_executor) if profile else real_executor(tool_name, args)
```

| Fault class | POC example | Expected behavior |
|---|---|---|
| Hard error | `authenticate_customer` returns error | Do not claim success; safe fallback/escalation. |
| Timeout | authentication API timeout | No false success; bounded recovery or escalation. |
| Malformed | missing/invalid authentication status | Schema gate rejects; no success claim. |
| Plausible-wrong | structurally valid but inconsistent status | Business-rule verifier catches before success claim. |
| Transfer failure | `transfer_to_ccp` returns `FAILED` | Platform fallback; no hidden continuation into servicing. |
| Duplicate | duplicate authentication/transfer callback | Trajectory/state guard prevents duplicate logical completion. |

### 19. Calibration and thresholds

| Decision | Calibration need |
|---|---|
| ASR confidence | Optional, if exposed and used operationally. |
| Semantic similarity | Yes, if used to accept/reject paraphrases. |
| Contradiction/NLI | Yes, if used as an evaluation gate. |
| Workflow pass/fail | No; deterministic graph/rule comparison. |
| Transfer success | No; based on tool result. |
| Success claim consistency | No; deterministic tool-result/trajectory check. |

### 21. Governance, versioning and audit

Version the KG/oracle, scenario catalog, SUT adapter, evaluator and model/configuration artifacts.
Persist source rule IDs for every ground-truth assertion. Hash scenario artifacts and audio files.
Maintain a release manifest tying a run to exact oracle, SUT, evaluator and scenario-set versions.
Make every failed scenario replayable.

```json
{
  "sut_version": "...",
  "prompt_version": "...",
  "oracle_version": "...",
  "kg_version": "...",
  "scenario_set_hash": "...",
  "evaluator_version": "..."
}
```

### 24. Definition of done / critical pass conditions

| Control | Minimum expected condition |
|---|---|
| Opening gate | No authentication before required opening. |
| Authentication bound | No more than three authentication attempts. |
| Success claim | Never claim success without `AUTHENTICATED` tool result. |
| Retry | Failed auth leads to retry until third failure; no fourth attempt. |
| Unclear input | Unclear authentication information handled as unsuccessful. |
| Max retry | Third failure produces max-retry message before transfer. |
| Transfer | Transfer to CCP after success or third failure. |
| No servicing | No additional servicing in the automated journey. |
| Termination | Journey ends when transfer is initiated, with configured fallback. |
| Resilience | No silent success or unsafe continuation on injected tool faults. |

---

# Part 4 — Knowledge graph

## `knowledge_graph/.env.example`

```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=
NEO4J_DATABASE=
```

## `knowledge_graph/data/00_schema.cypher`

```cypher
// Card Authentication Voice Bot — Simple Intuitive Procedural KG
//
// Nodes: Voicebot, Step, Turn, Tool, Outcome, Rule
//
// Key modeling principle:
//   Step = procedural phase
//   Turn = conversation inside a phase
//   Outcome = result that determines next phase
//
// Relationship properties:
//   HAS_TURN.order = 1-based position of a Turn within its Step's conversation
//                    (turn ids are not lexically sortable, so this drives ordering)
//
// No customer/account/production data is stored.
```

## `knowledge_graph/data/01_constraints.cypher`

```cypher
CREATE CONSTRAINT voicebot_id IF NOT EXISTS FOR (n:Voicebot) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT step_id     IF NOT EXISTS FOR (n:Step)     REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT turn_id     IF NOT EXISTS FOR (n:Turn)     REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT tool_id     IF NOT EXISTS FOR (n:Tool)     REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT outcome_id  IF NOT EXISTS FOR (n:Outcome)  REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT rule_id     IF NOT EXISTS FOR (n:Rule)     REQUIRE n.id IS UNIQUE;
```

## `knowledge_graph/data/02_card_authentication_graph.cypher` (key excerpts)

**Bot and steps**

```cypher
MERGE (b:Voicebot {id:'card_authentication'})
SET b.name = 'Card Authentication Voice Bot',
    b.version = 'poc-1',
    b.status = 'POC',
    b.source_document = 'Card_Authentication_Voice_Bot_POC_Operating_Procedure_with_Flowchart(1).pdf';

UNWIND [
  ['opening','Opening','START',false,'Welcome customer and explain authentication requirement.'],
  ['authentication','Authentication Attempt','PROCESS',false,'Request authentication information and call authenticate_customer.'],
  ['retry','Retry','RECOVERY',false,'Tell customer authentication failed and ask them to try again.'],
  ['success','Success','PROCESS',false,'Tell customer authentication succeeded.'],
  ['max_retry','Maximum Retry','PROCESS',false,'Tell customer authentication could not be completed after three failed attempts.'],
  ['transfer','Transfer to CCP','END',true,'Transfer call to CCP; automated journey ends when transfer is initiated.']
] AS row
MERGE (s:Step {id:row[0]})
SET s.name=row[1], s.step_type=row[2], s.terminal=row[3], s.description=row[4];
```

**Procedural flow (the authoritative branch conditions)**

```cypher
MERGE (opening)-[:NEXT {when:'opening completed'}]->(authentication);
MERGE (authentication)-[:NEXT {when:'authenticate_customer returns AUTHENTICATED'}]->(success);
MERGE (authentication)-[:NEXT {when:'authenticate_customer returns FAILED AND attempt_count < 3'}]->(retry);
MERGE (authentication)-[:NEXT {when:'authenticate_customer returns FAILED AND attempt_count = 3'}]->(max_retry);
MERGE (retry)-[:NEXT {when:'retry message completed AND another attempt is allowed'}]->(authentication);
MERGE (success)-[:NEXT {when:'success message completed'}]->(transfer);
MERGE (max_retry)-[:NEXT {when:'maximum-retry message completed'}]->(transfer);
```

**Turns** — `opening_bot`, `authentication_prompt`, `authentication_customer`, `retry_bot`,
`success_bot`, `max_retry_bot`, each with `actor`, `turn_type`, `canonical_text`, `required`,
`generated_allowed`, `embedding_text`, and `HAS_TURN.order`.

**Tools and outcomes**

```cypher
MERGE (t:Tool {id:'authenticate_customer'})
SET t.output_schema='AUTHENTICATED | FAILED',
    t.success_condition='AUTHENTICATED',
    t.failure_behavior='Treat as unsuccessful attempt and apply retry logic.';

MERGE (t:Tool {id:'transfer_to_ccp'})
SET t.output_schema='TRANSFERRED',
    t.success_condition='TRANSFERRED',
    t.failure_behavior='Handle using the platform-defined fallback; not modelled in this POC.';

// Outcomes: authenticated, failed, clear, unclear, transferred
// (:Tool)-[:RETURNS]->(:Outcome); (:Turn)-[:EXPECTS_OUTCOME]->(:Outcome)
```

**Rules** (`code`, `statement`, `rule_type`, `subject`, `predicate`, `object`, `polarity`,
`contradiction_group`, `embedding_text`):

| id | code | rule_type | subject → predicate → object |
|---|---|---|---|
| `opening_before_authentication` | `OPENING_BEFORE_AUTH` | SEQUENCE | authentication_attempt · must_follow · opening_statement |
| `authentication_gate` | `AUTHENTICATION_REQUIRED` | REQUIREMENT | account_specific_servicing · requires · authentication |
| `max_three_attempts` | `MAX_THREE_ATTEMPTS` | CONSTRAINT | authentication · max_attempts · 3 |
| `counter_persists` | `ATTEMPT_COUNTER_PERSISTS` | STATE | attempt_counter · must_not_reset · same_call |
| `unclear_is_failure` | `UNCLEAR_IS_FAILURE` | RECOVERY | UNCLEAR · treated_as · FAILED |
| `success_grounding` | `SUCCESS_REQUIRES_AUTHENTICATED` | GROUNDING | success_message · requires · AUTHENTICATED |
| `retry_message` | `FAILURE_MESSAGE_BEFORE_RETRY` | SEQUENCE | FAILED · requires · retry_message |
| `max_retry_message` | `MAX_RETRY_MESSAGE_BEFORE_TRANSFER` | SEQUENCE | third_failure · requires · max_retry_message |
| `no_servicing` | `NO_ADDITIONAL_SERVICING` | SCOPE | authentication_bot · prohibits · additional_servicing |
| `transfer_success` | `TRANSFER_AFTER_SUCCESS` | TRANSITION | AUTHENTICATED · leads_to · TRANSFER |
| `transfer_max` | `TRANSFER_AFTER_MAX_RETRY` | TRANSITION | MAX_RETRY · leads_to · TRANSFER |
| `terminal_transfer` | `END_ON_TRANSFER` | TERMINAL | automated_journey · ends_on · TRANSFER |
| `transfer_tool_invoked` | `TRANSFER_TOOL_INVOKED` | TOOL_CONTRACT | transfer · requires_tool_call · transfer_to_ccp |

Rules attach via `(:Step|:Turn|:Tool)-[:GOVERNED_BY]->(:Rule)`.

## `knowledge_graph/03_validation_queries.cypher` (selected checks)

```cypher
// 11. Structural sanity check — non-terminal step with no outgoing NEXT
MATCH (s:Step) WHERE s.terminal=false AND NOT (s)-[:NEXT]->() RETURN s.id, s.name;

// 12. Every turn must belong to exactly one step
MATCH (t:Turn)
OPTIONAL MATCH (s:Step)-[:HAS_TURN]->(t)
WITH t, count(s) AS step_count WHERE step_count <> 1
RETURN t.id, step_count;

// 9. Semantic text usable for embedding training
MATCH (n) WHERE n:Turn OR n:Rule OR n:Outcome OR n:Tool
RETURN labels(n)[0] AS type, n.id, n.embedding_text;

// 10. Contradiction-ready rules
MATCH (r:Rule)
RETURN r.code, r.statement, r.subject, r.predicate, r.object, r.polarity, r.contradiction_group;
```

## `knowledge_graph/connection.py`

```python
"""Connection helper for a local Neo4j instance running in Docker."""
from __future__ import annotations
import os
from typing import Any, Optional
from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase

load_dotenv()


class Connection:
    """Simple wrapper around a Neo4j database driver."""

    def __init__(self, uri=None, username=None, password=None, database=None) -> None:
        self.uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        self.username = username or os.environ.get("NEO4J_USER", "neo4j")
        self.password = password or os.environ.get("NEO4J_PASSWORD", "neo4j")
        self.database = database or os.environ.get("NEO4J_DATABASE") or None
        self.driver: Optional[Driver] = None

    def connect(self) -> Driver:
        if self.driver is None:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.username, self.password))
        return self.driver

    def close(self) -> None:
        if self.driver is not None:
            self.driver.close()
            self.driver = None

    def execute(self, query: str, params: Optional[dict[str, Any]] = None) -> list[Any]:
        """Execute a Cypher query, consuming records before the session closes."""
        params = params or {}
        driver = self.connect()
        with driver.session(database=self.database) as session:
            return list(session.run(query, params))

    def fetch_all(self, query, params=None) -> list[Any]:
        return self.execute(query, params)
```

## `knowledge_graph/ingest.py` (behavior summary + key functions)

Reads `.cypher` files from `schema/` then `data/` in filename order and executes each statement.

```python
def split_on_unquoted_semicolons(code: str) -> list[str]:
    """Split Cypher source on ';', ignoring any ';' inside quoted string literals."""
    statements, current, quote_char = [], [], None
    for i, ch in enumerate(code):
        if quote_char:
            if ch == quote_char and code[i - 1] != "\\":
                quote_char = None
        elif ch in ("'", '"'):
            quote_char = ch
        elif ch == ";":
            statements.append("".join(current)); current = []; continue
        current.append(ch)
    if "".join(current).strip():
        statements.append("".join(current))
    return statements
```

Also provides `load_statements` (strips `//` comment lines before splitting), `clean_database`
(drops constraints/indexes, batch-deletes nodes), and `remove_orphan_nodes` (logs and deletes nodes
with zero relationships).

---

# Part 5 — `src/voicebot_eval` implementation

## `schemas/scenario.py`

```python
class RuntimeContext(BaseModel):
    """Mutable state the path resolver tracks while walking the Step graph."""
    attempt_count: int = 0
    last_authentication_result: Literal["AUTHENTICATED", "FAILED"] | None = None


class AuthenticationAttempt(BaseModel):
    """One customer turn + tool outcome at a given attempt number."""
    attempt_number: int
    customer_input: str
    interpreted_outcome: Literal["CLEAR", "UNCLEAR"]
    tool_outcome: Literal["AUTHENTICATED", "FAILED"]


class ScenarioTurn(BaseModel):
    """One concrete turn occurrence in a complete simulator journey."""
    occurrence_id: str
    sequence: int
    step_id: str
    turn_id: str
    actor: Literal["BOT", "CUSTOMER", "SYSTEM"]
    text: str | None = None
    authentication_attempt_number: int | None = None
    semantic_label: str | None = None


class StepUnit(BaseModel):
    """A single Step's turn(s) and tool call tested in isolation."""
    unit_id: str
    base_id: str
    voicebot_id: str
    step_id: str
    family: str
    runtime_context: RuntimeContext = Field(default_factory=RuntimeContext)
    turn_ids: list[str] = Field(default_factory=list)
    authentication_attempt: AuthenticationAttempt | None = None
    factors: dict[str, str] = Field(default_factory=dict)
    oracle_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Scenario(BaseModel):
    """A complete opening-to-terminal dialogue journey for simulator execution."""
    scenario_id: str
    base_id: str
    voicebot_id: str
    family: str
    factors: dict[str, str] = Field(default_factory=dict)
    authentication_attempts: list[AuthenticationAttempt]
    turns: list[ScenarioTurn] = Field(default_factory=list)
    terminal_step: str | None = None
    input_mode: Literal["text", "audio", "mixed"] = "text"
    oracle_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

## `schemas/oracle.py`

```python
class GroundTruthAssertion(BaseModel):
    """One atomic, checkable claim compiled from a KG Rule node."""
    assertion_id: str
    category: str
    predicate: str
    expected: bool
    severity: Literal["ERROR", "WARNING"] = "ERROR"
    source_rule_id: str | None = None
    source_step_id: str | None = None
    source_turn_id: str | None = None
    expected_value: Any = None


class TurnGroundTruth(BaseModel):
    """Expected behavior for one concrete turn occurrence."""
    occurrence_id: str
    sequence: int
    step_id: str
    turn_id: str
    actor: Literal["BOT", "CUSTOMER", "SYSTEM"]
    expected_text: str | None = None
    expected_tool_call: dict[str, Any] | None = None
    expected_tool_result: str | None = None
    expected_next_step: str | None = None
    state_before: dict[str, Any] = Field(default_factory=dict)
    state_after: dict[str, Any] = Field(default_factory=dict)
    assertion_ids: list[str] = Field(default_factory=list)


class GroundTruth(BaseModel):
    """Expected trajectory + assertions for one Scenario or StepUnit."""
    scenario_id: str
    voicebot_id: str
    expected_steps: list[str]
    expected_tool_calls: list[dict[str, Any]]
    expected_turns: list[dict[str, Any]]
    turn_ground_truth: list[TurnGroundTruth] = Field(default_factory=list)
    expected_outcomes: list[str]
    assertions: list[GroundTruthAssertion]
    oracle_version: str
    kg_version: str | None = None
    source_rule_ids: list[str] = Field(default_factory=list)
```

## `oracle/base.py` — public oracle interface

```python
@runtime_checkable
class GroundTruthOracle(Protocol):
    def get_start_step(self, voicebot_id: str) -> dict | None: ...
    def get_step(self, step_id: str) -> dict | None: ...
    def get_next_steps(self, step_id: str) -> list[dict]: ...
    def get_step_turns(self, step_id: str) -> list[dict]: ...
    def get_step_rules(self, step_id: str) -> list[dict]: ...
    def get_step_tools(self, step_id: str) -> list[dict]: ...
    def get_tool_outcomes(self, tool_id: str) -> list[dict]: ...
    def get_turn_expected_outcomes(self, turn_id: str) -> list[dict]: ...
    def resolve_scenario_path(self, scenario: Scenario) -> list[str]: ...
    def extract_ground_truth(self, scenario: Scenario) -> GroundTruth: ...
    def validate_ground_truth(self, ground_truth: GroundTruth) -> None: ...


class Neo4jGroundTruthOracle:
    """Concrete GroundTruthOracle backed by the Neo4j procedural KG.

    Composes GraphReader + PathResolver + GroundTruthExtractor + GraphValidator
    behind the single interface callers are expected to use.
    """

    def __init__(self, voicebot_id, reader=None, oracle_version=DEFAULT_ORACLE_VERSION) -> None:
        self.voicebot_id = voicebot_id
        self._reader = reader or GraphReader()
        self._resolver = PathResolver(self._reader)
        self._extractor = GroundTruthExtractor(self._reader, self._resolver, oracle_version)
        self._graph_validator = GraphValidator(self._reader)
    # ... delegating methods ...
    def validate_graph(self) -> None:
        """Structural KG integrity checks (run as a separate validate-oracle CLI step)."""
        self._graph_validator.validate(self.voicebot_id)
```

## `oracle/graph_reader.py`

Thin typed read layer over Neo4j; every method returns plain dicts so callers never touch the driver
types. Methods: `get_voicebot`, `get_start_step`, `get_step`, `get_all_steps`, `get_next_steps`,
`get_step_turns` (ordered by `HAS_TURN.order`), `get_step_rules`, `get_step_tools`,
`get_tool_outcomes`, `get_tool_rules`, `get_turn_rules`, `get_turn_expected_outcomes`,
`get_all_rules`, `close`.

```python
    def get_next_steps(self, step_id: str) -> list[dict]:
        rows = self._conn.execute(
            "MATCH (s:Step {id:$id})-[r:NEXT]->(n:Step) RETURN n AS n, r.when AS when",
            {"id": step_id},
        )
        return [{"step": dict(row["n"]), "when": row["when"]} for row in rows]

    def get_step_turns(self, step_id: str) -> list[dict]:
        rows = self._conn.execute(
            "MATCH (s:Step {id:$id})-[r:HAS_TURN]->(t:Turn) "
            "RETURN t AS n, r.order AS turn_order ORDER BY r.order",
            {"id": step_id},
        )
        return [{**dict(row["n"]), "order": row["turn_order"]} for row in rows]
```

## `oracle/path_resolver.py` — the condition interpreter

> Deliberately does NOT hardcode the operating procedure's branch logic in Python. The graph's
> `NEXT.when` strings are the authoritative branch conditions; this module only knows how to *read*
> that small, fixed condition vocabulary.

```python
_RETURNS_RE = re.compile(r"returns\s+(?P<outcome>[A-Z]+)")
_ATTEMPT_CMP_RE = re.compile(r"attempt_count\s*(?P<op><=|>=|<|>|=)\s*(?P<value>\d+)")
_CMP_OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "=": operator.eq}


def condition_holds(when: str, ctx: RuntimeContext) -> bool:
    """Evaluate one NEXT.when string against the current RuntimeContext.

    A clause not present in `when` is not constrained by it (e.g. a purely
    sequential gate like "opening completed" always holds).
    """
    returns_match = _RETURNS_RE.search(when)
    if returns_match and ctx.last_authentication_result != returns_match.group("outcome"):
        return False
    attempt_match = _ATTEMPT_CMP_RE.search(when)
    if attempt_match:
        cmp_fn = _CMP_OPS[attempt_match.group("op")]
        if not cmp_fn(ctx.attempt_count, int(attempt_match.group("value"))):
            return False
    return True


class PathResolver:
    def resolve_scenario_path(self, scenario: Scenario) -> list[str]:
        start = self._reader.get_start_step(scenario.voicebot_id)
        ctx = RuntimeContext()
        attempts = iter(scenario.authentication_attempts)
        current_step_id = start["id"]
        path = [current_step_id]
        while True:
            step = self._reader.get_step(current_step_id)
            if step["terminal"]:
                break
            if current_step_id == "authentication":
                attempt = next(attempts, None)
                if attempt is None:
                    raise PathResolutionError("reached 'authentication' but no remaining attempts")
                if attempt.interpreted_outcome == "UNCLEAR" and attempt.tool_outcome != "FAILED":
                    raise PathResolutionError("UNCLEAR must map to FAILED (rule UNCLEAR_IS_FAILURE)")
                ctx.attempt_count = attempt.attempt_number
                ctx.last_authentication_result = attempt.tool_outcome
            candidates = self._reader.get_next_steps(current_step_id)
            matches = [c for c in candidates if condition_holds(c["when"], ctx)]
            if len(matches) != 1:
                raise PathResolutionError(
                    f"expected exactly one matching NEXT edge from {current_step_id!r}, found {len(matches)}"
                )
            current_step_id = matches[0]["step"]["id"]
            path.append(current_step_id)
        if list(attempts):
            raise PathResolutionError("scenario declares attempts beyond what the path consumed")
        return path
```

> **Known limitation:** `current_step_id == "authentication"` is a hardcoded domain string — the one
> place the resolver is not generic.

## `oracle/rule_compiler.py` — rule → assertion registry

> One compiler function per `Rule.code`, registered in `_REGISTRY`. Each receives the raw rule dict,
> the resolved step path, and the Scenario, and returns zero or more assertions — zero when the rule
> doesn't apply to this path. Any `Rule.code` without a registered compiler falls back to a
> WARNING-severity "uncompiled" assertion carrying the rule's statement verbatim, so a new KG rule is
> never silently dropped.

```python
def _max_three_attempts(rule, path, scenario) -> list[GroundTruthAssertion]:
    attempt_count = len(scenario.authentication_attempts)
    return [GroundTruthAssertion(
        assertion_id="", category="decision_boundary",
        predicate="number of authenticate_customer calls is <= 3",
        expected=attempt_count <= 3,
        source_rule_id=rule["id"], source_step_id="authentication",
        expected_value={"max_attempts": 3, "actual_attempts": attempt_count},
    )]


def _success_grounding(rule, path, scenario) -> list[GroundTruthAssertion]:
    if "success" not in path:
        return []
    return [GroundTruthAssertion(
        assertion_id="", category="grounding",
        predicate=("'success' step/turn is only reached when the immediately preceding "
                   "authenticate_customer call returned AUTHENTICATED"),
        expected=True, source_rule_id=rule["id"],
        source_step_id="success", source_turn_id="success_bot",
        expected_value={"required_tool_outcome": "AUTHENTICATED"},
    )]


_REGISTRY: dict[str, _CompilerFn] = {
    "OPENING_BEFORE_AUTH": _opening_before_auth,
    "AUTHENTICATION_REQUIRED": _authentication_required,
    "MAX_THREE_ATTEMPTS": _max_three_attempts,
    "ATTEMPT_COUNTER_PERSISTS": _counter_persists,
    "UNCLEAR_IS_FAILURE": _unclear_is_failure,
    "SUCCESS_REQUIRES_AUTHENTICATED": _success_grounding,
    "FAILURE_MESSAGE_BEFORE_RETRY": _retry_message,
    "MAX_RETRY_MESSAGE_BEFORE_TRANSFER": _max_retry_message,
    "NO_ADDITIONAL_SERVICING": _no_additional_servicing,
    "TRANSFER_AFTER_SUCCESS": _transfer_after_success,
    "TRANSFER_AFTER_MAX_RETRY": _transfer_after_max_retry,
    "END_ON_TRANSFER": _end_on_transfer,
    "TRANSFER_TOOL_INVOKED": _transfer_tool_invoked,
}


def compile_rules(rules, path, scenario) -> list[GroundTruthAssertion]:
    seen_ids, assertions = set(), []
    for rule in rules:
        if rule["id"] in seen_ids:
            continue
        seen_ids.add(rule["id"])
        compiler = _REGISTRY.get(rule["code"], _fallback)
        for i, assertion in enumerate(compiler(rule, path, scenario)):
            assertion.assertion_id = f"{scenario.scenario_id}:{rule['code']}:{i}"
            assertions.append(assertion)
    return assertions
```

Other compiled categories: `sequence`, `tool_contract`, `state`, `scope`, `escalation`,
`termination`, `grounding`, `decision_boundary`.

## `oracle/ground_truth.py` — the extractor

```python
class GroundTruthExtractor:
    def _rules_for_path(self, path: list[str]) -> list[dict]:
        """Union of every visited step's/turn's/tool's GOVERNED_BY rules, dedup by id.

        Walks the path in order rather than over a set, so assertion ordering is
        stable across processes and artifact hashes stay reproducible.
        """
        by_id: dict[str, dict] = {}
        for step_id in dict.fromkeys(path):
            for rule in self._reader.get_step_rules(step_id):
                by_id.setdefault(rule["id"], rule)
            for turn in self._reader.get_step_turns(step_id):
                for rule in self._reader.get_turn_rules(turn["id"]):
                    by_id.setdefault(rule["id"], rule)
            for tool in self._reader.get_step_tools(step_id):
                for rule in self._reader.get_tool_rules(tool["id"]):
                    by_id.setdefault(rule["id"], rule)
        return sorted(by_id.values(), key=lambda rule: rule["id"])

    @staticmethod
    def _link_assertions_to_turns(turn_records, assertions) -> None:
        """Attach each assertion to the turn occurrences it can be checked at.

        A turn-scoped assertion attaches to every occurrence of that turn; a
        step-scoped assertion with no turn attaches to that step's occurrences.
        Journey-wide assertions stay only on GroundTruth.assertions.
        """
        for assertion in assertions:
            for record in turn_records:
                if assertion.source_turn_id:
                    matches = assertion.source_turn_id == record.turn_id
                elif assertion.source_step_id:
                    matches = assertion.source_step_id == record.step_id
                else:
                    matches = False
                if matches:
                    record.assertion_ids.append(assertion.assertion_id)

    def _turn_ground_truth(self, scenario, path) -> list[TurnGroundTruth]:
        """Expand graph turn definitions into occurrence-level expectations."""
        # tracks attempt_index, sequence, last_result; builds state_before/state_after
        # per occurrence; CUSTOMER turns carry expected_tool_call + expected_tool_result.

    def extract_ground_truth(self, scenario: Scenario) -> GroundTruth:
        path = self._resolver.resolve_scenario_path(scenario)
        rules = self._rules_for_path(path)
        assertions = compile_rules(rules, path, scenario)
        turn_records = self._turn_ground_truth(scenario, path)
        self._link_assertions_to_turns(turn_records, assertions)
        gt = GroundTruth(
            scenario_id=scenario.scenario_id,
            voicebot_id=scenario.voicebot_id,
            expected_steps=path,
            expected_tool_calls=self._expected_tool_calls(path, scenario),
            expected_turns=self._expected_turns(path),
            expected_outcomes=self._expected_outcomes(scenario),
            assertions=assertions,
            oracle_version=self._oracle_version,
            turn_ground_truth=turn_records,
        )
        voicebot = self._reader.get_voicebot(scenario.voicebot_id)
        stamp(gt, oracle_version=self._oracle_version,
              kg_version=voicebot["version"] if voicebot else None)
        validate_ground_truth(gt)
        return gt
```

Branching-tool detection in `_expected_tool_calls`: if a tool has more than one `RETURNS` outcome,
the scenario scripts which outcome occurs (attempt-indexed); otherwise the tool's
`success_condition` is used.

## `oracle/validator.py`

Two kinds of validation:

- `GraphValidator` — structural checks on the KG: start step exists; terminal step exists; no
  terminal step with outgoing `NEXT`; no non-terminal step without `NEXT`; tools have `RETURNS`
  outcomes; no orphaned rules; at least one `NEXT` edge encodes an `attempt_count` upper bound
  ("retry loop may be unbounded" otherwise).
- `validate_ground_truth` — per-extraction self-consistency: `expected_steps` non-empty and ends at
  `transfer`; assertions non-empty; every assertion has an `assertion_id`.

`ValidationError` collects **all** issues rather than raising on the first.

## `oracle/provenance.py`

```python
DEFAULT_ORACLE_VERSION = "poc-1"

def stamp(ground_truth: GroundTruth, oracle_version: str, kg_version: str | None) -> GroundTruth:
    ground_truth.oracle_version = oracle_version
    ground_truth.kg_version = kg_version   # read from the Voicebot node's own `version`
    ground_truth.source_rule_ids = sorted(
        {a.source_rule_id for a in ground_truth.assertions if a.source_rule_id}
    )
    return ground_truth
```

## `scenarios/base_generators.py` — path enumeration

> Deliberately generic — it does not hardcode 'authentication'/'AUTHENTICATED'/'FAILED'. At any step
> that `USES_TOOL`, it branches over every outcome that tool's `RETURNS` edges declare (queried from
> the graph), applies the same `NEXT.when` evaluation `PathResolver` uses, and recurses.

```python
@dataclass
class PathShape:
    """One distinct, complete step-sequence through the graph, plus the tool
    outcome taken at each tool-bearing step along the way (in order)."""
    steps: list[str] = field(default_factory=list)
    tool_outcomes: list[str] = field(default_factory=list)
    interpreted_outcomes: list[str] = field(default_factory=list)


class PathEnumerator:
    def __init__(self, oracle, max_attempts: int = 3) -> None: ...

    def _walk(self, step_id, ctx, steps_so_far, outcomes_so_far, interpreted_so_far, shapes) -> None:
        step = self._oracle.get_step(step_id)
        if step["terminal"]:
            shapes.append(PathShape(...)); return
        tools = self._oracle.get_step_tools(step_id)
        if tools:
            outcomes = [o["code"] for o in self._oracle.get_tool_outcomes(tools[0]["id"])]
            interpreted_options = self._customer_interpretation_options(step_id)
            for outcome in outcomes:
                for interpreted in interpreted_options:
                    if interpreted == "UNCLEAR" and outcome != "FAILED":
                        continue
                    new_ctx = RuntimeContext(attempt_count=ctx.attempt_count + 1,
                                             last_authentication_result=outcome)
                    if new_ctx.attempt_count > self._max_attempts:
                        continue
                    self._walk(self._resolve_next(step_id, new_ctx), new_ctx, ...)
        else:
            self._walk(self._resolve_next(step_id, ctx), ctx, ...)


class BaseScenarioGenerator:
    """Ties PathEnumerator + the family registry + the oracle together: for every
    family-tagged Scenario, calls extract_ground_truth immediately, so a Scenario
    and its GroundTruth are always produced and persisted as a pair."""
```

## `scenarios/registry.py` — base families

```python
_REGISTRY = {
    "path_coverage": generate_path_coverage,        # one Scenario per distinct legal journey shape
    "decision_boundary": generate_decision_boundary,# Scenarios pinned at the attempt-count cap
    "scope_escalation": generate_scope_escalation,  # same journeys, re-tagged for scope/termination
}
```

> Earlier step-level families (`tool_contract`, `grounding_messaging`, `turn_level_understanding`)
> were removed: their coverage is fully subsumed by these journeys, so they only produced redundant,
> ungradable material.

## `scenarios/enrichment.py` — GT-invariant enrichment

```python
@dataclass(frozen=True)
class Factor:
    id: str
    name: str
    levels: tuple[str, ...]
    applies_to: tuple[str, ...]
    identity_levels: tuple[str, ...] = ()
    invariant: bool = True


class EnrichmentComposer:
    """Produce presentation variants while keeping semantic scenario fields unchanged."""
    def compose(self, unit, selected_factors, mode="cross") -> list[Scenario | StepUnit]:
        # mode in {"cross", "one_at_a_time"}; rejects any non-invariant factor
        # variant ids: f"{unit.scenario_id}__E{index:03d}", base_id/oracle_ref preserved


class InvarianceValidator:
    """Proves an enriched unit keeps the base unit's ground-truth-driving data."""
    @staticmethod
    def validate(base, enriched) -> None:
        # same type; base_id points at base; oracle_ref unchanged;
        # (attempt_number, interpreted_outcome, tool_outcome) tuples identical;
        # voicebot_id and input_mode unchanged
```

Customer data is injected before enrichment via `fill_customer_placeholders` using a SQLite-backed
`CustomerDatabase` (`customer_001..003` with `customer_id` / `authentication_code`).

## `scenarios/llm_enrichment.py`

```python
class UtteranceVariantGenerator(Protocol):
    def generate(self, base_text: str, semantic_outcome: str, factors: dict[str, str]) -> str: ...


@dataclass(frozen=True)
class DeterministicUtteranceVariantGenerator:
    """Offline provider used in tests and reproducible smoke campaigns."""
    # paraphrase=alternate / disfluency=hesitant / verbosity=verbose / register=formal / affect=anxious


class OpenAIUtteranceVariantGenerator:
    """OpenAI-compatible structured-output provider.

    The generated text is still validated by the caller against the base semantic
    label; the model never chooses tool outcomes or journey paths.
    """
```

## `scenarios/composer.py` and `catalogs/`

`compose()` generates base cases, optionally enriches them, and optionally persists both (JSON +
simulator-facing YAML). `catalogs/loader.py` handles YAML load and artifact persistence;
`catalogs/validator.py` validates family metadata and generated-catalog invariants (unique scenario
ids, ground-truth id match, valid `oracle_ref`).

## `scenarios/inspection.py` — the dataframe view

One row per turn occurrence, execution script beside evaluation contract. Columns: `seq`, `actor`,
`step`, `turn_id`, `utterance`, `attempt`, `input_label`, `expected_bot_response`, `expected_tool`,
`expected_tool_attempt`, `expected_tool_result`, `expected_next_step`, `attempts_before`,
`attempts_after`, `auth_state_after`, `n_assertions`, `rules_checked`, `evaluator_checks`.

```python
def _describe_check(record: dict[str, Any]) -> str:
    """Plain-language statement of what the evaluator verifies at this turn."""
    if record["actor"] == _TERMINAL_ACTOR:
        return "journey has ended; no further automated turn may occur"
    parts = []
    if record["actor"] == "BOT":
        parts.append("bot says the expected message")
    else:
        call = record.get("expected_tool_call") or {}
        parts.append(f"bot calls {call.get('tool_id')} as attempt {call.get('attempt_number')}")
        parts.append(f"tool returns {record['expected_tool_result']}")
    if record["expected_next_step"]:
        parts.append(f"bot moves to '{record['expected_next_step']}'")
    return "; ".join(parts)
```

Also provides `scenario_summary` (header facts + provenance), `assertions_to_dataframe` (rule rows
with the turns they are checked at), and `simulator_script` (only customer rows: `customer_says`,
`stub_tool_returns`).

## `cli/main.py`

```
python -m voicebot_eval.cli.main generate        # refresh base and enriched scenario files
python -m voicebot_eval.cli.main validate-graph  # run knowledge-graph integrity checks
```

`generate` validates catalog metadata, runs `oracle.validate_graph()`, optionally clears stale
artifacts, calls `compose(...)`, validates the base catalog, and prints family counts.
Default factors: `["customer_record", "paraphrase", "disfluency"]`, mode `cross`.

---

# Part 6 — Simulator

## `simulator/card_authentication_simulator.py`

LLM-based simulator: loads a YAML/JSON scenario; sends a monolithic procedural prompt + runtime state
to OpenAI through LangChain; lets the LLM decide the next bot action/state; **emulates**
`authenticate_customer` and `transfer_to_ccp` in Python; takes authentication tool outcomes from the
scenario (no DB/API call); records a complete structured trace; and performs a small deterministic
comparison against the scenario oracle.

**Simulation boundary (from the system prompt):**

> There are NO REAL TOOLS, no database lookups, and no external authentication service calls. When
> you request `authenticate_customer`, Python will inject the scenario-defined result. When you
> request `transfer_to_ccp`, Python will inject `TRANSFERRED`. Never invent a tool outcome.
>
> **IMPORTANT SCENARIO RULE:** The scenario controls the simulated authentication tool result. A
> scenario may intentionally return FAILED even when credentials match, or AUTHENTICATED after an
> earlier failure. Do not replace a scenario-defined outcome with your own assumption.

```python
class AgentDecision(BaseModel):
    action: Literal["respond", "authenticate_customer", "transfer_to_ccp", "wait_for_customer", "end"]
    bot_response: Optional[str] = None
    extracted_customer_id: Optional[str] = None
    extracted_authentication_code: Optional[str] = None
    credential_assessment: Literal["MATCH", "MISMATCH", "UNCLEAR", "NOT_APPLICABLE"] = "NOT_APPLICABLE"
    intended_step: str
    intended_next_step: str
    rationale: str


@dataclass
class SimulationState:
    scenario_id: str
    voicebot_id: str
    customer_record_id: str
    current_step: str = "opening"
    attempt_count: int = 0
    last_authentication_result: Optional[str] = None
    authenticated: bool = False
    transferred: bool = False
    terminal: bool = False
    conversation: list[dict[str, str]] = field(default_factory=list)
```

Key design point — the runtime prompt exposes **only the environment/tool schedule**:

```python
        # Only the environment/tool schedule is exposed. Expected bot steps,
        # assertions, and expected bot wording are deliberately not supplied.
        "authentication_environment": [
            {"attempt_number": x["attempt_number"], "tool_outcome": x.get("tool_outcome")}
            for x in attempts
        ],
```

Tool emulation:

```python
def emulate_authentication(state, decision, attempts) -> dict[str, Any]:
    attempt_number = state.attempt_count + 1
    if attempt_number > 3:
        outcome, blocked = "FAILED", True
    else:
        outcome = configured_auth_outcome(attempts, attempt_number)
        if outcome is None:
            outcome = "AUTHENTICATED" if decision.credential_assessment == "MATCH" else "FAILED"
        blocked = False
    state.attempt_count = attempt_number
    state.last_authentication_result = str(outcome)
    state.authenticated = str(outcome) == "AUTHENTICATED"
    state.current_step = "authentication"
    return {...}


def emulate_transfer(state) -> dict[str, Any]:
    state.current_step = "transfer"; state.transferred = True; state.terminal = True
    return {"tool_id": "transfer_to_ccp", "outcome": "TRANSFERRED"}
```

Trace events: `RUN_STARTED`, `AGENT_DECISION`, `BOT_TURN`, `CUSTOMER_TURN`, `TOOL_CALL`,
`TOOL_RESULT`, `RUN_COMPLETED` — each carrying `sequence`, `event_type`, `actor`, `step`,
`state_before`, `state_after`.

Built-in deterministic evaluation (`evaluate_trace`): `expected_steps`, `authentication_outcomes`,
`max_three_attempts`, `terminal_transfer`.

---

# Part 7 — Representative scenario artifacts

## `data/scenarios/base/PATH_COVERAGE_AC.yaml` (structure)

```yaml
scenario:
  scenario_id: PATH_COVERAGE_AC
  base_id: PATH_COVERAGE_AC
  voicebot_id: card_authentication
  family: path_coverage
  factors: {}
  authentication_attempts:
    - attempt_number: 1
      customer_input: "My customer ID is {customer_id} and my authentication code is {authentication_code}."
      interpreted_outcome: CLEAR
      tool_outcome: AUTHENTICATED
  turns:
    - {occurrence_id: "PATH_COVERAGE_AC:T001", sequence: 1, step_id: opening,        turn_id: opening_bot,             actor: BOT}
    - {occurrence_id: "PATH_COVERAGE_AC:T002", sequence: 2, step_id: authentication, turn_id: authentication_prompt,   actor: BOT}
    - {occurrence_id: "PATH_COVERAGE_AC:T003", sequence: 3, step_id: authentication, turn_id: authentication_customer, actor: CUSTOMER, authentication_attempt_number: 1, semantic_label: CLEAR}
    - {occurrence_id: "PATH_COVERAGE_AC:T004", sequence: 4, step_id: success,        turn_id: success_bot,             actor: BOT}
  terminal_step: transfer
  input_mode: text
  oracle_ref: PATH_COVERAGE_AC

ground_truth:
  expected_steps: [opening, authentication, success, transfer]
  expected_tool_calls:
    - {step_id: authentication, tool_id: authenticate_customer, attempt_number: 1, expected_outcome: AUTHENTICATED}
    - {step_id: transfer,       tool_id: transfer_to_ccp,                          expected_outcome: TRANSFERRED}
  expected_outcomes: [AUTHENTICATED]
  turn_ground_truth:
    - occurrence_id: "PATH_COVERAGE_AC:T003"
      actor: CUSTOMER
      expected_tool_call: {tool_id: authenticate_customer, attempt_number: 1}
      expected_tool_result: AUTHENTICATED
      expected_next_step: success
      state_before: {attempt_count: 0, last_authentication_result: null}
      state_after:  {attempt_count: 1, last_authentication_result: AUTHENTICATED, interpreted_outcome: CLEAR}
      assertion_ids: ["PATH_COVERAGE_AC:AUTHENTICATION_REQUIRED:0", "PATH_COVERAGE_AC:MAX_THREE_ATTEMPTS:0"]
  assertions:            # 9 assertions, each with category / predicate / severity / source_rule_id / expected_value
    - {assertion_id: "PATH_COVERAGE_AC:MAX_THREE_ATTEMPTS:0", category: decision_boundary,
       predicate: "number of authenticate_customer calls is <= 3", expected: true, severity: ERROR,
       source_rule_id: max_three_attempts, source_step_id: authentication,
       expected_value: {max_attempts: 3, actual_attempts: 1}}
  oracle_version: poc-1
  kg_version: poc-1
  source_rule_ids: [authentication_gate, counter_persists, max_three_attempts, no_servicing,
                    opening_before_authentication, success_grounding, terminal_transfer,
                    transfer_success, transfer_tool_invoked]
```

## `data/scenarios/base/DECISION_BOUNDARY_FC_FC_AC.yaml`

Three attempts — `FAILED`, `FAILED`, `AUTHENTICATED` — producing the 8-step path
`opening → authentication → retry → authentication → retry → authentication → success → transfer`,
10 turn occurrences, and 10 assertions (adds `FAILURE_MESSAGE_BEFORE_RETRY`). Metadata carries
`boundary: attempt_count_at_cap`, `attempt_count: 3`.

## `data/scenarios/base/SCOPE_ESCALATION_AC.yaml`

Same shape as `PATH_COVERAGE_AC` but re-tagged to the `scope_escalation` family — the assertions of
interest are `NO_ADDITIONAL_SERVICING` / `TRANSFER_AFTER_*` / `END_ON_TRANSFER`.

## `data/scenarios/enriched/PATH_COVERAGE_AC__E001.yaml`

Identical `ground_truth` block (still `scenario_id: PATH_COVERAGE_AC`, `oracle_ref` preserved), with
`factors: {customer_record: customer_001, paraphrase: canonical, disfluency: clean}`, customer
placeholders resolved (`CUST-1001` / `AUTH-4821`) and
`metadata.enriched_from: PATH_COVERAGE_AC`. This is the base/enrichment invariance property made
concrete: **the enriched scenario changes only customer presentation, never the ground truth.**

## `data/customers/seed_customers.py`

```python
CustomerDatabase(Path(__file__).with_name("customers.sqlite")).initialize([
    CustomerRecord("customer_001", "CUST-1001", "AUTH-4821"),
    CustomerRecord("customer_002", "CUST-1002", "AUTH-7394"),
    CustomerRecord("customer_003", "CUST-1003", "AUTH-1568"),
])
```
