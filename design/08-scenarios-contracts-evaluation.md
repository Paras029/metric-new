# Design Plan 08 — From graph to verdict

Plan 06 ended at a graph. This is the layer above it: scenarios, contracts, trace binding,
evaluation, and a UI. It is the phase the gap analysis (`grounding/06`) called *three insertions and
one inversion*, and it follows that shape.

---

## 1. What was actually missing

The old Scenario Generator enumerated paths, generated "expected tool" and "expected variant" fields,
wrote them to a workbook, and **never compared them to anything**. There was no evaluator, no
assertion, no verdict. Branch conditions were prose nothing parsed. There was no runtime state at
all, so `max_attempts` was a bound on the *search* rather than a claim about the *agent*. Nothing
linked an expectation to the policy sentence behind it, so nothing had severity or provenance, and a
prohibition could not be represented.

Four things close that, and each is a module here:

| Missing | Now |
|---|---|
| runtime state | `runtime/` — variables, peaks, call counts and order, replayed from a bound trace |
| structured predicates | `runtime/conditions.py` — `ON_VARIABLE`/`OPERATOR`/`COMPARE_TO`, evaluated, with `None` for undecided |
| typed expectations with provenance | `contract/` — assertions carrying severity, derivation level, source triples and spans |
| a trace entry point | `trace/` + `resolve.py` — `resolve_for_scenario` and `resolve_for_trace` behind one compiler |

---

## 2. The transferability seam: relations declare their own checks

The eval-poc compiled rules through a Python registry keyed by domain rule codes. It works, and it
does not travel — a second use case needs a second registry written by someone who knows both the
policy and the codebase. That is its own stated limitation and the strategy notes' named risk.

Here the **relation is the assertion kind**, and the relation declares it, in the ontology YAML:

```yaml
  - name: RULE_FORBIDS
    domain: [Rule]
    range: [Action, Outcome, State, Tool]
    checks:
      kind: action_forbidden
      dimension: policy
      scope: journey
      grouping: per_head
```

`contract/compile.py` owns only the mechanics that are the same whatever a relation means: grouping,
severity, derivation level, provenance, scope narrowing. A use case that adds a relation declares how
it is checked in the same file and the same edit — `schemas/card_auth.ontology.yaml` does exactly
this for `TRANSFERS_TO` — and nothing in the evaluator changes.

Two guards keep it honest. `kind` is validated at schema load against the graders that exist, so a
schema cannot invent a way of checking. And a relation must say either `checks:` or
`not_checkable: true`; one that says neither is reported as a contract note, because a relation that
quietly checks nothing is the difference between a use case that is covered and one that looks
covered.

---

## 3. Binding a trace: a mapping table, not an embedding problem

The production export settles what real telemetry carries. There is no `step_id`, no turn state, no
attempt counter, no terminal flag. But runtime state *is* there, inside tool payloads:

- `set_metadata` writes `("checkpoint", "check14Key")` — the agent narrating its own transitions;
- tool **arguments** carry the counters (`no_user_pref_counter: 1`);
- tool **outputs** carry the branch (`{"match": "NO_USER_RESPONSE"}`).

So binding is declared-then-lexical, and never guessed:

1. **declared** — `EMITTED_AS_*`, from a telemetry profile a person wrote (`profiles/*.yaml`);
2. **lexical** — the observed name folds to an entity's own name, within the same type;
3. **unbound** — reported, never guessed at and never dropped.

The profile is the seam for a second agent: `profiles/card_auth.telemetry.yaml` is 30 lines, and an
agent emitting different names needs another one and no code. Profile triples enter the graph as
declarations with `telemetry` as their method and the profile as their evidence — they are not
extractions and do not pretend to be.

The `checkpoint_variable` is declared in the profile rather than expected in the ontology, because
the field an agent narrates itself through is a telemetry artefact and no policy names it.

---

## 4. Four verdicts, not two

`pass` and `fail` are the easy two.

- **`not_applicable`** — the situation never arose. A retry rule on a run that never failed is not a
  pass; scoring it as one inflates every aggregate.
- **`undecided`** — the situation may have arisen and the trace cannot show it. This is the number
  worth watching: it is how much of the policy the instrumentation can actually hold an agent to.
  Folding it into pass or fail is how an evaluator comes to look confident about a blind spot.

There is no overall score, deliberately. Dimensions are reported separately because a run can reach
the right outcome while breaking a rule, and a single number destroys the distinction a reviewer
needs.

**Proof that it does not fabricate:** evaluating the real AOP production trace against the card-auth
ontology gives 0% binding coverage, zero passes and zero failures, and a list of seventeen things the
agent did that nothing can grade. They are different agents, and the evaluator says so instead of
inventing verdicts. That is a test (`test_evaluate.py::TestAnotherAgentsTrace`).

---

## 5. The review loop, and why nothing blocks until it runs

On a single-source policy almost every transition and threshold is a lone model reading of one
passage, so almost everything fails the witness bar and lands at `review`. An assertion resting on a
`review` triple is forced to `advisory` and **cannot fail an agent**.

That is correct, and on its own it is a dead end: a graph built from one document could never block
anything, and nobody would be asked to change that. So every `review` triple raises a question, and
answering it in the UI writes `questions.yaml` and rebuilds. On the working policy: 31 review
triples, all approved, and the planted violation goes from `advisory` to `error` with the build
`blocked`.

One bug found and fixed while building this, worth recording because it would have been silent:
answering a question resolves it, so it leaves the queue — and writing only the open questions
dropped the answer, making every approval undo itself on the next build. `questions.yaml` now keeps a
`resolved:` section, and a test asserts the property directly.

---

## 6. The UI

Python standard library, no Node, no framework, no CDN. `metric ui` and a browser is the whole
deployment, which matters because an internal network usually cannot reach a CDN and a tool that
renders unstyled behind the firewall is a tool nobody uses.

| Page | Answers |
|---|---|
| Overview | what this build produced, and under what identity |
| Workflow | the journey, as a layered SVG with rules on hover |
| Graph | every fact, filterable, each with the words it came from |
| Scenarios | what we would test, and what is not covered |
| Evaluations | what a real run did, verdict by verdict, with the policy behind each |
| Review | what still needs a person — approve or reject, rebuild immediately |

Every expectation on every page is one click from its source passage, with the quote highlighted.
The diagram is laid out in Python: layers by longest forward path, rows ordered by barycentre to cut
crossings, and back edges routed through empty space and a clear right-hand lane — a straight line
between two boxes crosses whatever sits between them, which on a retry loop is always something.

---

## 7. Where this fails, and what is done about it

| Failure | What is in place |
|---|---|
| Path explosion on a real graph | budgets, and truncation reported as a coverage gap with the budget that caused it — never a silent stop |
| A branch the walk missed | second pass gives every uncovered edge its own focused path |
| The ontology does not match the agent | binding coverage and an unbound list; 0% is visible, not quiet |
| Telemetry too thin to grade a rule | `undecided`, reported per dimension |
| Grading the transcript instead of the agent | utterances are observations with their own kind; a verdict never rests on one |
| An unreviewed extraction failing an agent | `advisory` severity, which cannot block |
| A relation nobody checks | `checks:` or `not_checkable: true`, or it is reported |
| Scenario and trace paths drifting apart | one compiler, one graph; a divergence would have to be a divergence in scope |
| An approval silently undoing itself | `resolved:` in `questions.yaml`, with a test |

Honest limits, not yet addressed:

- **`tool_called` is run-scoped, not state-scoped.** Pinning a call to a state needs checkpoint
  bindings that a trace may not carry. It still catches a tool never called at all.
- **A count-scoped prohibition is not gradable as a prohibition.** "must not make a fourth attempt"
  is `undecided` as `action_forbidden` — the grader cannot tell which call was the fourth — and the
  `count_limit` assertion catches it instead. Both are reported.
- **`FAILED` is returned by two tools and merges into one outcome.** The collision is reported
  (`integrity/outcome-collision`), but the merged outcome inherits a transition from one of them.
  Splitting it automatically would invent a distinction the corpus does not make.
- **Enrichment, DOE and invariance are not built.** The base/enrichment split is the next layer, and
  it needs the variation counts that are still marked *pending sign-off* in the old repo.

---

## 8. What comes next, in order

1. **An AOP profile and ontology.** We have real traces for one agent and a graph for another. Until
   they meet, every production number is measured against a policy the agent does not implement.
2. **The accuracy gate** — precision and recall against an annotation written by someone who did not
   write the prompts. Still the item on the critical path.
3. **Enrichment and DOE** — the base/enrichment split, pairwise coverage, risk weighting by
   materiality.
4. **A semantic oracle for `text_required`**, once there is a labelled cohort to calibrate it on.
   Containment is deterministic and honest; it is not enough for paraphrase-permitted language.
5. **Fault injection**, both into the agent (resilience) and into our own pipeline (do the detectors
   fire).
