# Design Plan 07 — Build notes: where the code differs from plan 06, and why

Plan 06 is the design. This records what the first build actually does where it departs from it,
with the reasoning, so the difference is a decision rather than a drift.

---

## 1. Determinism does not come from `temperature`

Plan 06 assumed the usual determinism controls. They no longer exist: `temperature`, `top_p` and
`top_k` are rejected outright by the current Claude models — a request carrying one returns a 400.
There is no sampling knob to pin.

What the build does instead:

- **`llm/cache.py` is the reproducibility mechanism.** A response is keyed by the exact request
  that produced it. Re-running a build over an unchanged corpus replays recorded responses and
  yields a byte-identical graph. `ReplayGateway` makes that guarantee enforceable: a cache miss is
  an error, so a "reproduction" cannot quietly become a new build.
- **Model variation is confined and measured, not hidden.** It exists only at the moment a request
  is first made. The reproducibility harness measures it by running with the cache bypassed.
- **Everything downstream is order-independent** — content-hash ids, the frozen glossary, canonical
  sorting — so residual variation shows up as a diff in triples rather than as ordering noise that
  makes every build look different.

The cache is a build artefact, not an optimisation. Deleting it does not change what the pipeline
means; it changes whether the last build can be reproduced.

**Server-side refusal fallbacks are deliberately not enabled.** A fallback answers from a different
model, and the model id is part of build identity — two builds would claim the same identity while
meaning different things. A refusal raises and the build stops.

---

## 2. The materiality bar moved from the gate to reconcile

Plan 06 §5.2 lists the materiality bar as admission criterion 5. It cannot run there. The bar asks
whether a triple has a **second witness**, and a witness may be in another passage or another
document — which is only known after duplicates have merged.

So `admit/gate.py` runs criteria 1–4 (schema, quote located, polarity, value present) and
`reconcile/dedup.py` applies the bar after merging. A high-materiality triple is admitted on a
deterministic origin **or** spans from more than one passage; otherwise it takes status `review`.

This introduced a fourth triple status, `review`, and a matching distinction on the graph:
`Graph.admitted` is what the build stands behind, `Graph.live` is everything it proposes. The
integrity checks read `live` — a fact held for review is still a fact the build found, and the
questions about it are exactly what a reviewer needs beside it.

---

## 3. Reconciliation is one ordered pass, not a bounded loop

Plan 06 §6 called for iterating to a fixed point, bounded at five rounds. The build does a single
ordered pass, because nothing feeds back: merging is keyed on `(head, relation, tail)`, and every
later stage only assigns statuses, which no key depends on. A second round would recompute the
first round's answer.

A bounded loop would have implied a convergence that does not exist. If a future stage rewrites
keys — entity merging, for instance — the loop comes back and this note is what says why.

---

## 4. Criterion 3 is met for the quantitative phrasings, and deliberately not for the third

Plan 06 §10.3 asks that "maximum of 3", "up to 3 total" and "must not make a fourth attempt"
collapse to **one** triple with three spans.

The first two do, and so does §4's "a hard maximum of 3 authentication attempts" — three phrasings,
one triple, three citations. `ontology/canonical.py` reduces a `Value` to number and unit, so
"3 authentication attempts", "3 total authentication attempts" and "3 attempts" agree while
"3 days" stays separate.

"must not make a fourth attempt" does **not** merge into it, and should not. Reading it as a limit
of three is an inference, and this pipeline does not infer. It stays a `Rule` with its own wording
and severity, and `integrity/numeric-restatement` raises a question when a numeric rule and a
threshold govern the same subject. A person confirms they agree.

This is a real reduction in scope against the plan, in exchange for not having an inference step
that nothing downstream could audit.

---

## 5. Two checks the plan did not anticipate

**`integrity/outcome-collision`.** `authenticate_customer` and `transfer_to_ccp` both return
`FAILED`. Entity identity is a hash of type and name, so those merge into one `Outcome` — meaning
one tool's failure would inherit the other's consequences. Splitting them automatically would
invent a distinction the corpus does not make. The build reports the collision and asks for the
names to be qualified.

**A numeric relaxation in the value check.** A source writing "three" supports a value of `3`.
Holding the digit form against it would drop a real fact over spelling. The comparison is still on
the value — `as_number` parses both forms and requires exact equality — so nothing but a numeric
match gets through this way.

---

## 6. What is built, and what is not

Built and tested against `grounding/07-card-authentication-policy.md`:

| Stage | Module |
|---|---|
| ontology, identity, canonical forms | `ontology/` + `schemas/*.yaml` |
| documents → passages | `corpus/` — markdown, text, pdf, docx, xlsx, image |
| deterministic harvest | `extract/harvest.py` |
| batching and the frozen glossary | `extract/batching.py`, `extract/glossary.py` |
| model boundary | `llm/` (gateway, cache, prompts, response schemas) |
| pass B extraction and the coverage audit | `extract/triples.py` |
| admission | `admit/` |
| reconciliation | `reconcile/` |
| outputs and the review loop | `reports.py`, `review.py`, `cli.py` |

The pdf, docx and xlsx readers are written but untested against real files — the optional
dependencies (`pypdf`, `python-docx`, `openpyxl`) are not installed in this environment, so only
the markdown path is covered by tests. Each refuses with a reason rather than reading as empty:
a scanned PDF, a partly-unreadable PDF and a workbook saved without cached formula values all stop
the build instead of silently contributing nothing.

Not yet built, in the order it matters:

1. **The reproducibility harness** — two cache-bypassed builds, diffed per relation.
2. **The annotation and the accuracy gate.** Precision and recall against an independent
   annotation. This is the item that needs someone other than whoever wrote the prompts, and it is
   on the critical path.
3. **The fault injectors** (plan 06 §8): polarity flip, rule split across a batch boundary,
   restated fact, contradictory value in a second document, detached table header, fabricated
   quote. Each proves a detector fires rather than merely existing.
4. **GEODE evaluation** (plan 05 §9): `normalize_graph`, `ProvenanceLedger`, `resolve_duplicates`,
   measured against what is here.
5. **The UI** — graph view, workflow view, triple editor. `review.py` is the v1 queue and is a file.

One known limit worth stating plainly: a PDF has no tables, only positioned glyphs, so the
header-into-every-cell rule that protects markdown, docx and xlsx cannot be applied there. A policy
whose constraints live in a PDF table needs the source document, not a better regex.

---

## 7. Decisions still open

These need an answer and are not blocking the current build:

- **Store.** File-backed JSON today. Neo4j becomes worth it when traversal queries outgrow sorted
  tuples, not before.
- **Gateway.** The build calls the Anthropic SDK directly through `llm/gateway.py`. If SafeChain is
  the required path, it goes behind the same `Gateway` protocol and nothing else changes.
- **Who annotates the golden corpus.** It cannot be whoever wrote the prompts.
