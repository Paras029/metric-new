# Design Plan 10 — The reverse mapping: conversation in, ground truth out

Plans 06–09 built the forward half and stopped one level short on the reverse half. This closes it.

---

## 1. What was missing

`resolve_for_trace` produced **one contract for a whole conversation**. That answers *did this run
comply?* It does not answer *at turn three, what should have happened next?* — and the second
question is the one a failure analysis, a reviewer and a regression suite all actually ask. Nothing
resolved ground truth at turn granularity, and nothing inferred state when the agent did not say it.

Measured before the change: 17 assertions for a 6-turn conversation, 0 contracts per turn.

---

## 2. The hinge: placing a turn in the graph

Everything a knowledge graph knows is anchored to a state. Until a turn is placed, none of it can be
brought to bear. `trace/states.py` places every turn by four mechanisms, tried in order:

| Method | How | Certain? |
|---|---|---|
| `checkpoint` | the agent wrote it through `set_metadata` | yes |
| `inferred` | what the turn *did* pins exactly one state | no |
| `ambiguous` | several states could account for it; all are listed | no |
| `carried` | nothing moved or revealed anything, so it is where it was | no |
| `none` | say so | no |

**A turn is not an atom.** The working trace writes `authenticating` and then `retry` inside one
turn. Collapsing that to a single state loses the hop and makes the tools called there look like they
belong somewhere else — which it did, producing three false findings before the binder was changed to
hold the visit *sequence*.

**Only a checkpoint is certain.** Inference is good enough to analyse with and not good enough to
accuse with, so every assertion on an uncertain turn is forced to advisory with the reason attached.
The strategy notes are explicit: a low-confidence binding must surface as uncertainty, never quietly
become a hard verdict.

---

## 3. The inverse index — "two of three gives you the third"

Forward, the graph says a state uses these tools and that a decision produces these outcomes.
Inverted:

- a **tool** → the states that could have called it (`USES_TOOL` read backwards)
- an **outcome** → the decision that produced it → the states that offer that decision
  (`HAS_OUTCOME` then `OFFERS_DECISION`, both backwards)
- the **previous state** → what is reachable from it

Intersect those three and usually one state survives. It is a dictionary, not a model.

**Measured.** Take the working trace, delete every checkpoint so the agent narrates nothing about
where it is, and ask the binder to place the turns anyway:

```
   turn 0 [none      0.00]  —                                      actual Opening and authentication
OK turn 1 [inferred  0.80]  Authentication attempts                actual Authentication attempts → …
OK turn 2 [inferred  0.80]  Authentication attempts                actual Authentication attempts → …
OK turn 3 [inferred  0.80]  Authentication attempts                actual Authentication attempts → …
OK turn 4 [inferred  0.80]  Authentication attempts                actual Authentication attempts → …
OK turn 5 [inferred  0.80]  Transfer and end of automated journey  actual Transfer and end …

recovered the entry state for 5/6 turns with no checkpoints at all
```

Turn 0 is the opening, where nothing happened — left unplaced rather than guessed. This is the test
that matters for the reverse mapping and it is `test_groundtruth.py::TestRecoveringStateWithout
Checkpoints`.

---

## 4. Ground truth for a turn

Once placed, the graph is read forward from that state and nothing else is mixed in:

| From | Relation |
|---|---|
| which tools belong here | `USES_TOOL` |
| which outcomes they may return | `RETURNS` |
| where it may go next | `HAS_NEXT_STEP`, and `LEADS_TO` from each outcome |
| which rules are in force | `GOVERNED_BY` |
| what must be said verbatim | `HAS_TURN` → `HAS_CANONICAL_TEXT` |
| whether this is an ending | `IS_TERMINAL` |

That is the ground truth. `TurnTruth` carries it beside what the turn actually did, the contract
narrowed to it, and the findings from comparing the two: a tool the state does not declare, an
outcome no tool here returns, a transition the graph does not allow, required wording not said, a
silent turn in a non-terminal state.

On the working trace this catches the planted violation a second way — the fourth attempt jumps from
`Authentication attempts` straight to `Maximum retry reached`, skipping the retry state policy
requires passing through. The `count_limit` assertion catches the count; the turn walk catches the
trajectory.

---

## 5. What this is not

It is worth being direct, because the question was asked directly: **this is not the old Scenario
Generator.** That tool read an Excel intake, walked states depth-first, had an LLM write prose, issued
a workbook, and asked a model "which scenario does this transcript look like?". Its `expected_tool`
and `expected_variant` fields were written to a spreadsheet and never compared to anything; branch
conditions were prose nothing parsed; there was no runtime state, no assertion, no verdict, no
provenance on any expectation, and prohibitions were unrepresentable.

What is here, against that list:

| Old | Now |
|---|---|
| Excel intake sheet | policy documents → triples with evidence spans |
| `outcome_condition` as prose | `ON_VARIABLE` / `OPERATOR` / `COMPARE_TO`, evaluated |
| no runtime state | variables, peaks, call counts and order, replayed from telemetry |
| no rule layer | `RULE_REQUIRES` / `RULE_FORBIDS` with severity and source spans |
| expectations with no provenance | every assertion names its triples and their quotes |
| one entry point: a workbook it wrote | `resolve_for_scenario`, `resolve_for_trace`, `resolve_turns` |
| "which scenario does this look like?" | "where in the graph is this turn, and what did policy require here?" |
| no evaluator | graders, four verdicts, dimensions reported separately |

The path enumeration is the one piece deliberately kept, and even that changed: revisit limits now
come from the policy's own thresholds rather than bounding the search by hand.

---

## 6. Limits

- **Certainty needs instrumentation.** Inference places turns well, but only a checkpoint lets a turn
  fail an agent. Getting first-class state attributes on the span is worth more than any amount of
  cleverness here — it is the difference between analysing a run and grading it.
- **Ambiguity is reported, not resolved.** When several states could account for a turn, all are
  listed and confidence is divided. That is honest and it is not an answer; a semantic binder would
  be, once there is a labelled cohort to calibrate one on.
- **`carried` is an assumption.** A turn that reveals nothing is assumed not to have moved. It is
  labelled, and it cannot grade.
- **The AOP graph is observed, so its turns place poorly** — one state, learned from one trace. That
  is a corpus problem, not a mechanism problem: run discovery over a cohort and it improves.

---

## 7. Next

1. **Ask for state attributes on the span.** One field would move most turns from `inferred` to
   `checkpoint`, and with them from analysable to gradable.
2. **Discovery over a real trace cohort**, then the AOP operating procedure.
3. **The accuracy gate** — unchanged, still the critical path.
