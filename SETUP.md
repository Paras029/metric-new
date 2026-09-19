# Setup

Three ways to run this, in increasing order of what they need from you. Start at the
first — it works with no API key and no network, and it exercises the whole pipeline.

---

## 1. Offline, from the recorded extraction

```bash
git clone https://github.com/Paras029/metric-new && cd metric-new
python -m venv .venv && source .venv/bin/activate     # Python 3.11 or newer
pip install -e ".[dev]"

pytest -q                     # 258 tests
metric bases                  # what this graph can be asked, and what was generated
metric evaluate --turns       # grade the traces, turn by turn
metric ui                     # http://127.0.0.1:8765
```

`corpus.yaml` names `fixtures/card_auth.extraction.json`, a recorded model extraction, so
nothing reaches the network. Everything below — scenarios, contracts, trace binding,
verdicts, the UI — runs from it.

The build writes to `build/`:

| File | What it holds |
|---|---|
| `graph.json` | admitted triples, canonically sorted, each with its spans and how it was found |
| `quarantine.json` | every rejected candidate, the criterion it failed, the quote it claimed |
| `scenarios.json` | the bases, the graph's capabilities, the taxonomy, and the settings used |
| `plan.json` | the variants each base would be run under |
| `evaluations.json` | verdicts per trace, and ground truth per turn |
| `questions.yaml` | what the pipeline could not settle — **edit it in place and re-run** |
| `manifest.json` | build identity: corpus, schema, prompts, model, settings, code |
| `report.md` | what went wrong first, then the counts |

### Python

3.11 or newer. One runtime dependency, `pyyaml`. The extras are optional:

```bash
pip install -e .            # core: ingest, evaluate, UI
pip install -e ".[llm]"     # + the anthropic SDK, to call the model
pip install -e ".[docs]"    # + pdf, docx, xlsx readers
pip install -e ".[dev]"     # + pytest, ruff, mypy
```

There is no Node, no build step and no CDN. The UI is `http.server` and inline CSS.

---

## 2. Calling the model directly

Remove `fixture:` from `corpus.yaml`, then:

```bash
export ANTHROPIC_API_KEY=sk-...        # or: ant auth login
pip install -e ".[llm]"
metric ingest --corpus corpus.yaml --out build
```

Every response is written to `.metric/llm-cache`, keyed by the exact request. A rebuild
serves from the cache and costs nothing. To guarantee a rebuild is the *same* build:

```bash
metric ingest --corpus corpus.yaml --replay    # a cache miss is an error
```

---

## 3. Inside American Express, through SafeChain

Model traffic does not go to a vendor endpoint. Set the provider:

```yaml
# metric.yaml
llm:
  provider: safechain
  model: claude-opus-5
```

```yaml
# corpus.yaml
use_case: card_authentication    # travels with every call, for entitlement and audit
```

```bash
export SAFECHAIN_ENDPOINT=https://...
export SAFECHAIN_APP_ID=...
pip install safechain           # internal index
```

That is the whole change. `Gateway` is one method — a system prompt, a user prompt, a
JSON schema — so extraction, admission, the cache and build identity are all written
against the protocol rather than a vendor. `src/metric/llm/safechain.py` is the only file
that knows SafeChain exists.

It supports both routes the SDK exposes, `invoke` and `chat.completions.create`, and
picks whichever the client has. For anything else, wrap it and pass it in:

```python
from metric.llm.safechain import SafeChainGateway
gateway = SafeChainGateway(client=my_wrapped_client, use_case="card_authentication")
```

Three things stay exactly as they are on the vendor route, because they are properties of
the evaluation and not of the transport: the cache key is computed from the same payload,
so a graph built here and one built against the SDK are the *same build*; a refusal
raises rather than falling back to another model; and no sampling controls are sent.

`app_id` and `use_case` are part of the gateway's identity, so a build made under a
different entitlement is recorded as a different build.

---

## Configuring it

`metric.yaml` holds every tunable in the pipeline, and ships with the defaults written
out. It is picked up automatically when it sits beside the corpus file.

```bash
metric settings              # what a build would use, and its digest
```

```yaml
corpus:     { batch_chars, min_batch_chars, furniture_min_repeats, context_passages }
admission:  { min_quote_chars, check_polarity, check_value, numeric_word_tolerance }
witness:    { enabled, materiality, min_passages }
scenario:   { max_depth, max_paths, default_revisits, reach_for_uncovered }
binding:    { allow_inference, allow_carry, confidence }
llm:        { provider, model, effort, max_tokens, cache }
enrich:     { arrangement, adverse_run, seed }
```

The whole file is hashed into build identity. **Two builds that used different settings
are different builds and say so** — the same rule the schema, the prompts and the model
already follow. A misspelled key is an error, not a shrug: silently ignoring it would
leave you believing you had changed something.

The two worth knowing about:

- `witness.enabled: false` removes the review queue's reason to exist. Every
  high-materiality fact resting on a single model reading goes straight into the graph
  and can block an agent. Turn it off only for a corpus that is already human-reviewed.
- `binding.allow_inference: false` and `allow_carry: false` grade only the turns the
  agent narrated about itself. Stricter, smaller, and defensible as a first deployment.

---

## A new use case

Five files, in the order you will write them.

**1. A corpus file.** Copy `corpus.yaml`. It says what to ingest and what to grade.

**2. An ontology extension.** Core (`schemas/core.ontology.yaml`) has 41 relations and
rarely needs changing. A use case adds its own in a file of the same shape:

```yaml
relations:
  - name: TRANSFERS_TO
    domain: [State]
    range: [Queue]
    materiality: high
    checks: { kind: transition_expected, dimension: trajectory, scope: state }
```

Every relation declares **how it is graded**, beside its domain and range. A relation
with neither `checks:` nor `not_checkable: true` is reported rather than silently graded
by nothing. Entity types are open — they are use-case specific and the schema does not
fixate them.

```bash
metric schema --schema schemas/core.ontology.yaml --extend schemas/yours.ontology.yaml
```

**3. A telemetry profile**, binding the ontology to what the agent actually emits:

```yaml
checkpoint_variable: checkpoint
tools:
  verify_identity: [check_14key, check_ANI]
```

If you have traces and no profile, draft one from them:

```bash
metric discover traces/*.json --name yours --use-case "Your agent"
```

That writes a profile and an *observed* structure. Structure learned from traces enters
the graph marked `telemetry`, and anything resting only on telemetry is forced to
advisory — it would pass by construction, and a verdict that cannot fail is not a verdict.

**4. A factor catalogue** (optional), for how the agent meets each situation:

```yaml
factors:
  - name: clarity
    levels: [clear, hesitant, garbled]
    adverse: garbled
    applies_to: { families: [traversal] }     # relevance: where this factor means anything
profiles:
  smoke: { factors: [clarity], arrangement: crossed }
```

**5. Run it.**

```bash
metric bases --corpus corpus.yaml     # what your graph can be asked
metric plan  --corpus corpus.yaml     # the runs that implies
metric ui    --corpus corpus.yaml
```

`metric bases` is the one to read first. It prints the capabilities your graph exposes
and the categories admissible from them. **A category is admissible only if the graph
exposes the capability it needs** — a policy stating no prohibitions generates no
prohibition material and says so, rather than reporting a category at zero.

---

## The review loop

The build stops short of claiming things it cannot support, and puts them in
`build/questions.yaml`:

```yaml
- id: a1b2c3d4
  question: "…rests on a single unreviewed reading"
  answer: ""        # approve | reject
```

Edit and re-run, or use the **Review** page in `metric ui`, which records the decision and
rebuilds immediately. Approving an expectation is the moment it stops advising and
becomes able to fail an agent — so it is one action, not a file edit plus a remembered
command.

Decisions survive. A resolved question is kept in a `resolved:` section, so an approval
does not silently undo itself on the next build.

---

## Attribution, once runs come back

`metric plan` produces the runs. Run them through your agent however you reach it, then
bring back one record per run:

```json
[{"variant": "a1b2", "scenario": "c3d4", "levels": {"asr": "heavy_noise"}, "passed": false}]
```

```bash
metric attribute results.json
```

Every rate carries a Wilson interval, every comparison an odds ratio with its interval,
and the whole family is corrected with Benjamini–Hochberg. A cell too small to compare is
named rather than dropped. Four of five passing is not 80% — at that sample size the
interval runs from 38% to 96%, and printing 80% invites a decision the data cannot
support.

Turning a chosen level into actual text is the one piece of application glue:

```python
from metric.enrich.materialize import register

def voice(question, levels):
    ...  # make `garbled` read garbled
    return text, ()          # nothing left unrendered

register("voice", voice)
```

The default materialiser is the identity and reports every level as *unrendered*, which
is honest: a run made under it varied nothing, and nothing should be attributed to a
column that never reached the agent.

---

## Checks

```bash
pytest -q
ruff check src tests
mypy --strict src
```

## Troubleshooting

**`CacheMiss` under `--replay`** — the request changed. The prompt, the schema, the model
or the settings differ from the recorded build. That is the mechanism working: a rebuild
must not quietly become a new build.

**0% binding coverage** — the telemetry profile does not match these traces, so nothing
was placed in the graph. This is deliberate: evaluating a trace from a different agent
gives no verdicts rather than confident nonsense. Run `metric discover` over the traces
to draft a matching profile.

**Bases quarantined after answer recovery** — a generator and the triples disagree.
`metric bases` prints the disagreement for each. Treat it as a bug in the generator or a
corruption in the graph, not as noise; that is what the check is for.

**`tool_absence` generated nothing** — some state declares no tools, so the world is
open, and an undeclared tool cannot be told apart from a gap in the corpus. Generating it
anyway would fail an agent for following the policy correctly.
