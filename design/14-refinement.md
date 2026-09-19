# Design Plan 14 — What a name is, and what a rule has to do

Three complaints, one root cause.

*"The ingestion pipeline resolves to a lot of questions"* — 49 of them on a five-page
policy. *"The entities should be properly written and crisp, not sentences."* *"A lot of
useless verbiage in the UI."*

The first two are the same problem seen from two ends, and the accuracy gate had already
measured it: strict precision 70%, relaxed 75%, and the gap was entirely names.

---

## 1. Where the questions came from

Broken down, the 49 were not 49 problems:

| | |
|---|---|
| 31 | high-materiality facts resting on one passage — **real decisions** |
| 15 | "this rule is attached to anything" — **one problem, asked fifteen times** |
| 3 | genuine gaps in the source — **real decisions** |

The 15 split further, and this is the part worth reading:

**Eight came from prose that is not policy.** The working corpus file carries the policy
*and* this repository's own notes about why it is a good first ingestion target —
including a table whose rows read *"What it contains: 'maximum of 3', 'up to 3 total',
'must not make a fourth' | Which ingestion problem it exercises: …"*. Written in the same
imperative voice as the policy. The extractor found rules there because there are
sentences there shaped exactly like rules.

No amount of extraction quality fixes that. **What counts as policy is a fact about the
corpus**, and the corpus file is where it belongs.

**Seven were restatements.** §1 summarises the rules, §7 lists them again as an evaluation
checklist. Each restatement became its own node, so "the bot must not perform any other
servicing activity", "does not perform additional servicing within the POC" and "the bot
does not perform any additional servicing itself" were three rules.

---

## 2. Section scope

`skip_sections:` and `sections:` on a document in the corpus file, matched against the
heading path every passage already carries — by prefix, case-insensitively, so `"3"`
selects `## 3. Operating procedure` and everything under it.

Ten passages of commentary left the corpus. **20 rules became 14, and 15 rule-scope
questions became 9.** No policy was lost; the test asserts every dropped passage is under
the excluded heading.

This is the cheapest fix in the repository and it needed no model.

---

## 3. What a name is

An entity named with the whole sentence it was found in is not named. `refine/names.py`
decides that deterministically — a Rule of more than five words, or any name containing a
modal or a negation, or one ending a sentence — and then tries two repairs in order.

**The label.** Policy documents name their own rules: `**Retry control:** Enforce a hard
maximum of 3 authentication attempts.` Where a surface carries a short label before a
colon, that label *is* the name. Four rules renamed, no model involved.

**The model.** What is left needs to know that "must not perform any other servicing
activity" and "does not perform additional servicing within the POC" are one rule. That is
a judgement about meaning and it is exactly what a model call is for. It returns a crisp
name and optionally an existing entity this one restates, **chosen from a closed list**, so
a merge target cannot be invented.

Renaming changes an entity's id, because identity is a content hash of type and name. So
this runs before reconciliation, two entities that land on one id merge, and a build whose
names changed is a different build with different question ids — which is correct and worth
knowing before running it over a corpus someone has already reviewed.

**The model half is unexercised here.** This container has no API key, so the ten names
that need a judgement are reported as unresolved rather than guessed at. That is the
honest outcome and the mechanism is tested against a stub.

### A bug this found

`FixtureGateway` answered the naming prompt. It records an *extraction*, has nothing to say
about naming, and returned `{"triples": []}` — a well-formed answer to a question it was
never asked, which the caller read as "the model found nothing" rather than "the fixture
has no answer". It now raises `FixtureMiss` for any stage it has no recording for, and
`answers:` in a fixture file is how a stage gets one.

---

## 4. Rules that assert nothing

Nine of the fourteen remaining rules carried exactly two things: their own text
(`RULE_STATES`) and a severity. Nothing was governed by them. They required, forbade and
bounded nothing.

Such a rule **cannot compile to an assertion**, cannot fail an agent, and cannot be acted
on. Each one raised a question whose only sensible answer was "yes, that is useless".

They are inert, and the treatment follows from what they actually are — a *recall defect*.
The extractor found "the bot must not perform any other servicing" and recorded that the
sentence exists without recording what it forbids:

- **Out of the graph**, because a node that can produce no assertion is a node a reviewer
  must read and dismiss.
- **One question, not nine**, naming all of them with their text quoted. Nine identical
  questions is one question asked nine times.
- **Schema-driven**: inert means no outgoing relation declaring a `checks:` and nothing
  `GOVERNED_BY` it. A use case that adds a checkable relation gets this for free.

**14 rules became 5. All nine rule-scope questions became one.**

---

## 5. What moved, and what did not

| | before | after |
|---|---|---|
| open questions | 49 | 35 |
| of which real decisions | 34 | 34 |
| rules | 20 | 5 |
| entities | 45 | 29 |
| accuracy (strict P / R) | 70% / 70% | 70% / 70% |

**The accuracy is unchanged, and that is the honest headline.** Everything above removed
*noise* — phantom nodes, duplicate assertions, a reviewer's time — without changing a single
fact the gate scores. The graph got legible, not more correct.

Making it more correct needs the model half of the naming pass (to merge the restatements
that carry real clauses) and the four genuine recall misses the gate already names. Neither
is served by the work in this plan, and saying so is better than implying the question
count was the problem.

---

## 6. The UI

Every page opened with a paragraph explaining the philosophy behind it. That belongs in
these documents, which is where it now is. `views.py` lost about 7% of its size and every
page lost its lede except where the text does one of three jobs:

- **a legend** — the workflow diagram's dashed-outline/heavy-outline key;
- **a consequence** — "Approve → it can fail an agent. Reject → it leaves the graph.",
  because that is what the button does;
- **an empty state** — what to add to the corpus file when a panel has nothing to show.

Numbers are labelled and otherwise left alone.

---

## 7. Limits

- **The naming model pass is built and unmeasured.** Ten names in the working build still
  read as sentences. Whether a model merges restatements well, or over-merges two rules
  that differ in a detail, is unknown — and over-merging is the worse failure, which is why
  `same_as` is a closed list and the prompt says to leave it empty when in doubt.
- **Pruning an inert rule loses the sentence.** It is quoted in the question, but if the
  rule was genuinely missed rather than restated, recovering it means reading that question
  and editing the corpus. The gate's recall number is the check on this.
- **Section scope is per document and by heading.** A document whose non-policy content is
  interleaved rather than sectioned cannot be scoped this way.
- **31 review questions remain and should.** They are single-witness high-materiality facts
  in a thin corpus — a property of the source, not a defect. Reducing them by fiat would
  remove the reason the review queue exists.

---

## 8. Next

1. **Run the naming pass against a model** and measure what it merges, and what it merges
   wrongly.
2. **The four recall misses** the accuracy gate names — one `USES_TOOL` and three Turn
   wordings.
3. **An independent annotation**, still the highest-value item and still a data task.
