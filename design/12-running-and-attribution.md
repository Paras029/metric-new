# Design Plan 12 — Running a plan, and attributing what comes back

Plan 11 ended with one limit named above the rest: *attribution has no runs yet. It takes
a cohort someone actually ran; there is still no simulator turning a planned variant into
a real conversation. That is the next thing worth building, and it is now the only thing
between `metric plan` and `metric attribute`.*

This closes it, and two things came out of doing so that were not on the list.

---

## 1. The shape, which is mostly refusals

`run/` drives a planned variant against an agent and produces a `Trace` — the same type
`read_galileo_export` returns. Grading happens afterwards, through `evaluate_trace`, the
same function that grades a conversation lifted out of production.

That is the whole architectural claim and it is worth stating why. A synthetic benchmark
that grades itself by its own route drifts away from the production evaluation it is
supposed to predict, silently, and the drift is invisible because both numbers keep
going up. Sending a simulated run down the production path means binding, state
placement, ground truth and grading are shared, and a defect in any of them shows up in
both directions at once.

Three seams, each one method wide:

| Protocol | What an installation supplies |
|---|---|
| `Agent` / `Session` | how to reach the system under test |
| `Customer` | what the situation makes someone say |
| `Materialiser` | how a chosen level becomes text |

The runner never sees the contract. What the *customer* says is allowed to come from the
base — a test case is entitled to know which situation it is staging, that is what a base
is — but what the agent was supposed to *do* is resolved independently, from the graph.

---

## 2. Four bugs a clean baseline caught

`GraphAgent` walks the same graph it will be graded against, so a clean one passes by
construction and that passing says nothing about any real agent. It is not there to score
well. It is there so that **a failure with no flaw injected means the harness is wrong**,
which is the only way to tell a defect in the evaluator from a defect in the thing
evaluated.

It earned its place immediately. The first clean run failed, four times, for four
different reasons.

**1. The reference agent did everything the policy permitted and nothing it owed.** It
called the tools states declare through `USES_TOOL` and ignored `REQUIRES_ACTION →
INVOKES`. A policy states obligations both ways. *(Agent bug.)*

**2. A turn reported one state's tools under the next state's name.** The checkpoint was
computed after the move rather than before it, so every turn was misplaced by one hop.
*(Agent bug, and the subtlest — the trace looked entirely plausible.)*

**3. The agent emitted entity ids where a real agent emits a wire name.** `Tool:ca655cb813`
instead of `authenticate_customer`. The binder resolved nothing, every tool read as
uncalled, and a clean agent failed for not calling a tool it had just called. *(Agent bug,
and a useful one: it proves the telemetry binding layer is load-bearing rather than
decorative.)*

**4. The conversation ended when the customer's script did.** An agent moves at the end of
its turn, so the state it moves *into* — very often the one that has to transfer, or say
the closing wording — never got a turn of its own. Capping the silence instead was tried
and is worse: it cuts off an agent still making progress, and a run cut short of an ending
is indistinguishable from one that stalled. Only the turn budget ends a call now.
*(Harness bug.)*

And one in the evaluator, found the same way:

**5. "The turn produced no tool call" fired on states that have no tools.** A state whose
whole job is to speak — an opening, a retry prompt — is *supposed* to be silent. The
finding now requires the state to declare tools. *(Evaluator bug, and it had been there
since plan 10.)*

With those fixed, the flaw matrix behaves:

| Injected | Result |
|---|---|
| *(none)* | passes, gradable |
| `no_checkpoint` | **no usable runs at all** — nothing to attribute |
| `ignore_limit` | fails `terminal_expected` |
| `jump` | fails `transition_allowed` ×3, names each hop |
| `stall` | fails `terminal_expected` |
| `extra_tool` | fails, names the tool and the state that does not declare it |
| `skip_wording` | fails, quotes the wording not said |

`no_checkpoint` is the one to read twice. An agent that never narrates its position
produces a cohort of 180 runs and **zero** that can be attributed. That is the designed
behaviour — only a checkpoint can fail an agent — and it is the strongest argument in the
repository for instrumenting an agent properly.

---

## 3. What a run has to survive to be counted

Two gates, and both exist because the alternative flatters.

**Gradable** — at least one turn the agent placed itself. A run with none tells you
nothing, and counting it as a pass lets poor instrumentation read as good behaviour.

**Staged** — the run touched at least one entity the base is about. A conversation can run
to completion, bind perfectly and fail an assertion without ever reaching the thing under
test: the customer pressed for a forbidden action and the agent was somewhere else
entirely. Counting that as a failure blames the agent for the harness.

The staging check is deliberately weak and says so. It catches *the situation never
arose*. It cannot confirm the situation arose **as the base intended**, and nothing here
can — that is a real limit of synthetic evaluation, not an omission.

`Run.passed` also changed. It was "no failing verdict"; it is now "no failing verdict
**and** no finding on a gradable turn". The evaluator has two routes — compiled assertions
for what the contract states, the turn walk for what the graph required at a position —
and counting only the first let an agent calling tools it had no business calling pass
with the finding printed underneath it.

---

## 4. The confound, and why a marginal comparison is not enough

The end-to-end test: build an agent that misbehaves under exactly one level,
`asr=heavy_noise`, tell nothing downstream, and see what comes back. 180 runs, 126 usable.

**Marginal attribution found five things.**

```
asr=clean          helps  100% vs 53%   OR 100.95   q=0.009
asr=heavy_noise    harms    0% vs 100%  OR   0.00   q=0.000
asr=mild_noise     helps  100% vs 63%   OR  44.47   q=0.024
history=none       helps   87% vs 60%   OR   4.36   q=0.016
history=prior_turns harms  60% vs 87%   OR   0.23   q=0.016
```

The agent has no reaction to `history` whatsoever. Nothing is wrong with the arithmetic —
a pairwise covering array does not balance every factor within every other's levels, so
`history=prior_turns` sat alongside `heavy_noise` more often than `history=none` did and
inherited its failures. **A marginal comparison cannot tell an effect from the company it
keeps**, and a design built to be economical guarantees some of that company.

`regression.py` fits all levels jointly, so each coefficient is that level's effect with
the others held fixed:

```
pseudo-R² 0.871 over 126 runs, ridge 1.0
asr=heavy_noise  harms (vs clean)  OR 0.012  [0.4%, 3.8%]  q=0.0000
```

One finding. The right one. `history=prior_turns` falls to q = 0.97.

Both are reported, and where they disagree the report says so in as many words, because
the disagreement is information: it tells you the design did not balance those two
columns, which is worth knowing before the next study is planned.

Three details in the fit that are not decoration:

- **Ridge is not optional.** A level under which every run failed — the case most worth
  reporting — is perfectly separable, and unpenalised logistic regression sends its
  coefficient to infinity and never converges. The penalty biases towards zero, making
  findings conservative rather than generous, and it is reported.
- **The intercept is never penalised.** Shrinking it pulls the model's baseline towards a
  50% pass rate, which is a claim about nothing.
- **The reference level is stated on every coefficient.** Without it the number is
  unlabelled.

---

## 5. The materialiser stops being inert

Plan 11 shipped the boundary and the identity default, which varies nothing and says so.
`enrich/voice.py` is one worked renderer: hesitation, ASR mishearing, persona, prior
history, paraphrase. It is deliberately a worked example rather than a mechanism, because
there is no mechanism to have — making a transcript read as though it came through a noisy
line depends on the language, the channel and the recogniser, and every substitution in
there is a guess a team with real transcripts would replace.

What it does not do matters more: it never touches what the situation *is*. A materialiser
that edited the situation would be changing ground truth from inside the presentation
layer, and the attribution that came back would be measuring the renderer.

---

## 6. Limits

- **The reference agent is a fixture, not evidence.** It walks the graph it is graded
  against. Every number in §4 measures the harness, not an agent. Pointing this at a real
  agent needs an `Agent` adapter, and the first real cohort is where the interesting
  failures will be.
- **Staging is checked weakly.** "The run touched something the base is about" is a long
  way from "the situation arose as intended", and a run can satisfy the first while
  testing nothing.
- **The scripted customer is thin outside traversal.** Categories other than
  `journey_path` and `threshold_boundary` get a generic follow-up or two. `ModelCustomer`
  is the answer and is built but unmeasured — nothing yet checks that a model playing a
  garbled customer produces something an ASR would actually emit.
- **Ridge intervals are approximate.** The usual caveat for penalised likelihood, and the
  alternative is no interval on exactly the coefficients that matter most.
- **No interaction terms.** The model is additive, so "fails only when the line is bad
  *and* the customer is confused" would show as two weak main effects. The design is
  pairwise, which is the right data for it; the model is not yet fitting it.
- **The accuracy gate is still the critical path.** Everything above rests on the graph
  being right, and nothing here measures that.

---

## 7. Next

1. **The accuracy gate.** Precision and recall of the extraction, annotated by someone who
   did not write the prompts. It has been named first for three plans now and it is time.
2. **An `Agent` adapter for a real system**, and the first cohort that means something.
3. **Interaction terms**, once there is a cohort big enough to fit them.
4. **A `ModelCustomer` study** — does a model playing a garbled caller produce transcripts
   an ASR would actually emit, or a literary impression of one?
