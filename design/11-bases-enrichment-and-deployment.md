# Design Plan 11 — The base taxonomy, the enrichment design space, and deployment

Plans 06–10 built ingestion, contracts, evaluation and the reverse mapping. This one
closes four gaps, three of which were named directly: scenario generation was not doing
what the book does, enrichment was missing most of its design space, nothing in the
pipeline was configurable, and it could not be deployed inside the bank.

---

## 1. What was wrong with scenario generation

The book derives its taxonomy **from the graph outward** — "start from the knowledge
graph, ask which kinds of facts it holds, then ask which questions each kind of fact can
support" — and gates each category on a **capability** the graph must expose. Eighteen
categories in five families, each recording its required capability, its ground-truth
primitive, its answer type and an honest status.

What was here was journey-path enumeration. One category, roughly, of eighteen. Every
other kind of fact in the graph — thresholds, prohibitions, obligations, fixed wording,
ordering — was extracted, admitted, cited, compiled into assertions, and then generated
nothing.

That is not a small gap. A policy that says "at most three attempts" produced a
`count_limit` assertion but no scenario that *makes* a fourth attempt. The graph knew the
rule and the test space never exercised it.

### What replaced it

The book's eighteen categories are for a question-answering store: recall, ranking,
cross-table aggregation. Ours holds an operating procedure, so the facts are different
and the categories derived from them are different. **The derivation is the same, and so
is the rule that makes it portable.**

`scenario/capability.py` reads twelve capabilities off the relations the graph actually
holds — `path`, `branch`, `threshold`, `condition`, `obligation`, `prohibition`,
`canonical_text`, `tools`, `outcomes`, `ordered_sequence`, `terminal`, `policy`. Nothing
is hardcoded per use case.

`scenario/taxonomy.py` is eleven categories in six families, each naming the capabilities
it needs:

| Category | Family | Answer | Needs |
|---|---|---|---|
| `journey_path` | traversal | path | `path` |
| `branch_outcome` | traversal | state | `branch`, `path` |
| `terminal_reachability` | traversal | bool | `path`, `terminal` |
| `threshold_boundary` | boundary | int | `threshold` |
| `condition_branch` | boundary | outcome | `condition` |
| `required_action` | obligation | bool | `obligation` |
| `canonical_text` | obligation | text | `canonical_text` |
| `forbidden_action` | prohibition | bool | `prohibition` |
| `tool_absence` | prohibition | bool | `tools` |
| `transition_absence` | prohibition | bool | `path` |
| `ordering` | sequence | list | `ordered_sequence` |

On the card-authentication policy: **6 journey paths became 32 bases across 5 families.**
`condition_branch` is inadmissible and says why — the graph holds no `Condition` with a
variable and an operator.

Adding a category is a row in the table plus a generator. It becomes admissible wherever
a graph happens to support it, with no per-use-case wiring.

### Why capability gating matters more than it sounds

The alternative is to generate every category and let the empty ones come back empty.
That reports zero coverage of a category the corpus never supported, which is
indistinguishable from a bug — and worse, invites someone to "fix" it by inventing the
missing facts.

`tool_absence` is the sharp case. It generates "at this state, ask for what this tool
does; the state does not declare it, so the agent must not call it". That is only a valid
test under a **closed world** — when every acting state declares its tools. If half the
states are silent, an undeclared tool is as likely to be a gap in the corpus as a
prohibition, and the test would fail an agent for following the policy correctly. So the
generator asks first, and on the current corpus stays silent and says so.

---

## 2. The functionality check

The book calls this the part most worth stealing, and it is: *before a generated question
is admitted, recover the answer from the store and confirm it equals the stated ground
truth.*

A generator that walks an index the builder filled wrongly produces confident,
well-formed, incorrect test material, and nothing downstream can tell. Recovery by a
second route is what makes that visible.

Every generator reads the graph through `graph.out`, `graph.by_relation` and `Journey` —
all of which read indexes built once at construction. Every check scans `graph.live`, the
flat triple list, touching no index. A base that disagrees is quarantined with the
disagreement recorded, the same treatment a rejected triple gets.

**It found something on its first run.** Twenty-five bases failed — not because a
generator was wrong, but because the *checker* read `graph.admitted` while the generators
read `graph.live`. Anything held for review disagreed by construction. The fix is one
line and the lesson is the mechanism's: independence of *route* is what is wanted, not
independence of *population*. The regression test is
`test_bases.py::test_a_check_reads_the_same_population_the_generator_did`.

Four more tests make a generator and the triples disagree on purpose — a threshold base
that calls a fourth attempt allowed against a limit of three, a path claiming a hop
nothing declares, a prohibition base naming a rule that forbids nothing — and assert the
base does not survive.

---

## 3. Enrichment: what was missing

Invariance was here. Four things from the book's design space were not.

**Relevance (`applies_to`).** A factor now names the families, answer types or categories
it is meaningful for, and it is applied automatically when the design is built. Numeric
framing means nothing to a base whose answer is a route through the graph. Crossing it in
does not merely waste runs — it spends the design's budget on cells that cannot fail for
the reason the column claims to measure, and every attribution drawn from that column is
diluted by them.

This changed what coverage *means*. Reporting against the full catalogue would charge the
design for pairs relevance ruled out, and no plan could ever be complete. The denominator
is now the pairs the bases in hand could actually have exercised.

One bug found writing the tests: an `applies_to` naming only `excludes` was treated as
selecting nothing, so the factor silently vanished from every base — the same failure as
forgetting to declare it. An exclusion-only specification now means "everywhere except
these".

**`level_overrides` and profiles.** The book's three levels of customisation, in order:
*select* factors (relevance filters the rest), *override* a factor's level vocabulary so a
domain reads in its own terms without forking the shared catalogue, *add* a factor as a
plain YAML entry. `catalogs/voice.factors.yaml` ships three profiles — `smoke`, `ivr`
(which renames the ASR levels), `regression` (which fixes the arrangement).

An override that drops the adverse level drops the adverse run with it, rather than
emitting a row naming a level the factor no longer has.

**Crossed and embedded arrangements.** Crossed pairs every base with every row: exhaustive
per base, cost grows with base count. Embedded promotes the base to a factor: fixed suite
size, and failures attributable to the base item itself.

Embedding under a modest budget can leave bases under-represented or absent entirely,
which is the one way the arrangement quietly misleads. The resolution is the conservative
one the book recommends — the base is a **balanced blocking factor**, equal runs each,
with presentation factors spread within that allocation from a rotating offset. A budget
smaller than the base count gives every base one run and says so, rather than dropping
some.

**The materialize boundary.** *Selecting a factor is data; rendering its levels is code.*
The design writes `clarity=garbled` into a variant; making a prompt actually read garbled
is domain work that depends on the channel, the language and how the agent is reached.
`enrich/materialize.py` is the seam. The default is the identity and reports every level
as **unrendered** — honest rather than useful, because a run made under it varied nothing,
and nothing should be attributed to a column that never reached the agent.

---

## 4. Customising every step

Every stage had numbers in it — batch size, quote floor, revisit limits, confidence
weights — and they were module constants. Invisible to whoever has to defend them, and
changing one meant editing code and losing the connection to the build it applied to.

`metric.yaml` is now all of them, in seven sections, shipped with the defaults written
out so the file is documentation as much as configuration. A test asserts it still equals
the defaults, so it cannot drift into being wrong.

**The whole file is hashed into build identity.** Two builds that used different settings
are different builds and say so — the same rule the schema, the prompts and the model
already follow.

A misspelled key is an error rather than a shrug: silently ignoring it would leave the
operator believing they had changed something. So is a floor above its ceiling, and an
unknown provider.

A setting nothing reads is documentation, not configuration, so
`test_settings.py::TestSettingsReachTheStages` pins the ones with teeth to the functions
that read them.

Two are worth knowing about because they can turn off a safeguard:

- `witness.enabled: false` removes the review queue's reason to exist. Every
  high-materiality fact resting on one model reading goes straight into the graph and can
  block an agent.
- `binding.allow_inference: false` grades only turns the agent narrated about itself.
  Stricter, smaller, and defensible as a first deployment.

---

## 5. Deploying inside the bank

Model traffic at American Express goes through SafeChain, which owns authentication,
entitlement, routing, inspection and the audit record. A pipeline that calls
`anthropic.Anthropic()` is not deployable there, whatever else is true about it.

`src/metric/llm/safechain.py` is the only file that knows SafeChain exists, and
`provider: safechain` is the whole switch. That is the payoff of `Gateway` being one
method taking a system prompt, a user prompt and a JSON schema: extraction, admission, the
cache and build identity are written against the protocol rather than a vendor.

Three properties are held identical to the vendor route, because they belong to the
evaluation rather than the transport, and each has a test:

- **The cache key is computed from the same payload.** A graph built through SafeChain and
  one built against the SDK are the *same build* when the model and prompts match.
- **A refusal raises.** No fallback model. A silent substitution would let two builds
  claim one identity while meaning different things.
- **No sampling controls are sent.**

`app_id` and `use_case` travel with every call — SafeChain entitles and attributes by
them, and they end up in the audit record a model risk review will ask for — and they are
part of the gateway's identity, so a build made under a different entitlement is recorded
as a different build.

Both client shapes the SDK exposes are supported (`invoke`, `chat.completions.create`).
An unrecognised response envelope is an error, not a guess: guessing wrong yields an empty
extraction that looks like a quiet policy.

---

## 6. Attribution

The design exists to make one question answerable, and nothing answered it. `attribution.py`
does, and it is small because the statistics are only honest given the design upstream.

Three things it refuses to do:

- **No bare pass rates.** Every rate carries a Wilson interval. Four of five is not 80% ±
  nothing; the interval runs from 38% to 96%.
- **No unadjusted comparisons.** Dozens of tests at a nominal 5% produce a finding by
  chance. Benjamini–Hochberg across the family. The test that pins this runs twenty null
  comparisons and asserts nothing is reported.
- **No effect without a direction and a size.** An odds ratio with its interval, with a
  Haldane–Anscombe correction so a zero cell — every run at one level failing, the case
  most worth reporting — gives a finite interval rather than infinity.

A cell too small to compare is named, not dropped.

**Weak-link attribution** needs no statistics: within a failing run, the first component in
execution order whose output was wrong is the one to fix. Everything after it was reasoning
from bad input, and a report listing every turn with a finding makes the fourth consequence
look as important as the cause.

---

## 7. Limits

- **Attribution has no runs yet.** It takes a cohort someone actually ran; there is still
  no simulator turning a planned variant into a real conversation. That is the next thing
  worth building, and it is now the only thing between `metric plan` and `metric attribute`.
- **Space-filling designs are not built.** The book minimises a φp criterion over the
  continuous unit hypercube and discretises, which maximises statistical power at fixed
  budget. Greedy pairwise is what is here: deterministic, honest about its coverage, and a
  few rows larger than optimal. φp is the successor, not a fix.
- **The default materialiser varies nothing.** Every design column is inert until an
  installation registers a renderer. This is stated in the output rather than hidden, but
  it means the current plan measures less than its size suggests.
- **`condition_branch` is unexercised.** No corpus here holds a `Condition` with a
  variable and an operator, so the generator is written and untested against real material.
- **The accuracy gate is still the critical path.** Precision and recall of the extraction,
  measured by someone who did not write the prompts. Everything above rests on the graph
  being right, and nothing here measures that.

---

## 8. Next

1. **A simulator** — turn a planned variant into an actual run, so `attribute` has input.
2. **The accuracy gate** — unchanged, still first in importance if not in order.
3. **State attributes on the span.** One field moves most turns from `inferred` to
   `checkpoint`, and with them from analysable to gradable.
4. **φp space-filling designs**, once there are enough runs for the power argument to bite.
