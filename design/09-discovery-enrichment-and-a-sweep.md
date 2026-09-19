# Design Plan 09 — Discovery, enrichment, and what a sweep of the code found

Plan 08 left three things at the top of the list: an ontology for the agent we actually have traces
of, the enrichment layer, and whatever a hard look at the code turned up. This is all three.

---

## 1. Discovery: what to do when there is telemetry and no policy

The AOP User Identification agent is the one we have real production traces for. There is no
operating procedure for it in this repository, and writing one from the telemetry would be
fabricating policy — the exact failure this whole design exists to avoid.

So discovery does the honest half. `metric discover` reads traces and recovers **structure**:

```
$ metric discover grounding/03-otel-trace-sample-galileo.json \
    --name aop_user_identification --use-case "AOP User Identification"
wrote profiles/aop_user_identification.telemetry.yaml
wrote observed/aop_user_identification.observed.yaml
  7 tools, 5 outcomes, 1 capabilities, 1 states from `checkpoint`
  other checkpoint candidates: checkpoint_14key
  these describe the agent, not policy — nothing here can fail it
```

Two files, both for a person to edit: a telemetry profile with every observed name mapped to itself
and ready to be renamed, and an observation file holding the structure.

**Finding the journey variable.** The agent writes its position through `set_metadata`, and its
counters arrive as tool arguments. Only explicit writes are candidates — a counter the agent was
*given* is state, but it is not the agent saying where it has got to. Values that are numbers or
booleans are counters and flags, so `check_fullssn_or_cm15_called=true` is excluded and
`checkpoint=check14Key` is not. Candidates a variable was seen with only once still count: a short
conversation may simply not have moved yet, and requiring two values would mean no single trace could
ever reveal the journey. The runner-up candidates are named in the file so the guess is reviewable.

**The circularity guard.** A rule learned by watching an agent cannot be used to fail that agent — it
passes by construction. Everything discovery produces carries `telemetry` as its method, and the
contract compiler forces any assertion whose sources are *all* telemetry to `advisory`, with the
reason attached:

> learned from watching this agent, so it cannot fail it — an expectation derived from behaviour
> passes by construction

`corpus-aop.yaml` is a corpus with no documents at all, which is a legitimate and important state:
we can see everything the agent does and have nothing to hold it to. The overview page says so in
those words rather than reporting "0 sections read" and leaving the reader to work it out.

**What it bought.** Binding coverage on the production trace went from **0% to 96%**, with only
`checkpoint` itself unbound (it is a telemetry field, not an ontology concept). Every verdict is
advisory. That is the correct and useful picture: the instrumentation is good enough to grade this
agent thoroughly, and there is no policy to grade it against.

---

## 2. Enrichment: varying how the agent meets a situation

The book's base/enrichment split. A **base** fixes the policy situation and the contract that
applies. **Enrichment** varies presentation — a hesitant customer, a garbled transcript, a longer
history — without changing what is required.

`catalogs/voice.factors.yaml` declares the factors, human-owned like the ontology, because which
conditions matter is a property of the use case. Four fields do work:

- `levels` — what can vary.
- `adverse` — the level that stresses the agent most.
- `invariant: false` — **this factor changes what is required, not just how it is presented.** A tool
  timeout does not change how the agent should phrase something; it changes its obligations. The
  planner excludes those and says why, rather than mixing them in and producing a variant graded
  against a contract that never applied to it.

`covering_array` gives pairwise coverage: every pair of levels appears together in at least one run.
On the voice catalogue that is **10 runs covering all 45 level pairs**, against 54 for the full
cross; the saving compounds as factors are added. The algorithm is greedy rather than optimal and
deterministic on purpose — a test plan that changes size between runs cannot be compared with the
last one.

**Test volume is derived, not decreed.** The old generator had `VARIATIONS_BY_MATERIALITY` marked
*placeholder — pending MRMG sign-off*, and it was the only thing connecting risk to effort. Here a
scenario's weight comes from its own contract: a scenario whose assertions can actually block gets
one extra run with every factor at its adverse level. Today no scenario gets one, because nothing can
block until it has been approved in review — which is the coupling working, and the UI says so.

**The invariance property is structural.** A contract is resolved from the scenario, never from the
variant, so a level cannot reach it. `test_enrich.py` asserts it anyway: the moment enrichment can
touch a contract, a failure stops being attributable to the level that caused it.

---

## 3. What the sweep found

Four real problems, all measured rather than guessed at.

**Graph lookups were quadratic.** `label()` and `entity()` were linear scans over the entity tuple,
and a page render calls them thousands of times. Measured at 3,000 entities: 0.146s of pure lookup.
Indexed: 0.0006s, and 10,000 entities now costs 2ms. The indexes are derived and excluded from
equality and serialisation, so they cannot make two graphs that should be identical differ.

**Integrity checking was quadratic.** `_evidence_for` scanned every live triple once per question.
At 2,400 entities: 0.178s. With an adjacency index: 0.0087s, and 8,000 entities in 30ms.

**Contracts were recompiled per scenario.** `Workspace` resolved a contract for every scenario to
decide its weight, and each resolution compiled the entire graph. Compilation is now separated from
narrowing — `compile_all` once, `narrow` per scenario — which is both faster and the clearer shape.

**Quarantine had nowhere to be read.** It is one of the three outputs and the UI showed only a count.
There is now a page: every rejected candidate grouped by the criterion it failed, with the quote it
claimed. A criterion suddenly rejecting far more than it used to is how a broken extractor is found,
and that is not visible in a number.

Smaller things: observation files are now shape-validated on load rather than failing deep inside the
merge; a `limit` parameter on `plan()` that no caller used was removed rather than left as
speculation; the build now writes `scenarios.json`, `plan.json` and `evaluations.json` alongside the
graph, and the report carries a test-space and evaluations section, because a graph without the test
space it implies is half an artefact.

---

## 4. Where this still falls short

- **One trace is a thin corpus.** Discovery over a single six-turn conversation finds one state and
  no transitions. It is built to take many traces at once and should be run over a real cohort before
  anyone reads the shape as the agent's shape.
- **Pairwise is the floor, not the ceiling.** Three-way coverage, risk weighting beyond the single
  adverse run, and Sobol designs are the progression the strategy notes lay out. Pairwise first is
  the right order; nothing here forecloses the rest.
- **Enrichment produces a plan, not runs.** Turning a variant into an actual conversation needs a
  simulator, which is the next component and not this one.
- **The adverse run is one row.** Every factor at its hardest is the worst *corner*, not the worst
  interaction. For a scenario that matters, a sweep would be better than a corner; that needs the
  measured cost of a run to justify.

---

## 5. Next, in order

1. **Run discovery over a real trace cohort**, and get the AOP operating procedure. Those two
   together are what turn an observed graph into ground truth.
2. **The accuracy gate** — precision and recall against an annotation by someone who did not write
   the prompts. Unchanged, still the critical path.
3. **A simulator**, so a variant becomes a run rather than a row in a plan.
4. **A semantic oracle for `text_required`**, once a labelled cohort exists to calibrate it on.
5. **Fault injection**, into the agent for resilience and into this pipeline to prove the detectors
   fire.
