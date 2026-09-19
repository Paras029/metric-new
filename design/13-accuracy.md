# Design Plan 13 — Is the graph right?

Named first in the "next" list of plans 09, 10, 11 and 12, and deferred each time in
favour of something more visible. This builds it, runs it, and the answer is worse than
the rest of the repository would lead you to expect.

---

## 1. Why nothing else could substitute for it

The pipeline has a lot of checks and every one of them is a consistency check.

| Check | What it actually confirms |
|---|---|
| admission gate | the model's claim is located in the source text |
| witness bar | a high-materiality fact rests on more than one passage |
| conflict detection | the graph does not contradict itself |
| capability gating | no category is generated that the graph cannot support |
| the functionality check | a base's answer can be recovered from the triples twice |
| the clean baseline | the evaluator agrees with the graph about a known-good agent |

Every row is a statement about internal consistency. **A confidently wrong graph passes
all of them.** If the extraction reads "the bot may make up to 3 attempts" as a threshold
on the wrong subject, the span is real, the quote is located, nothing conflicts, the
category is admissible, the answer recovers, and the reference agent — which reads the
same graph — agrees. The error is invisible from inside.

So the only thing that can detect it is a reading of the same source by someone who is not
the pipeline.

---

## 2. What the gate measures, and what it refuses to

**Precision and recall are not averaged.** A false positive is a fact the pipeline
invented, and it becomes an expectation an agent is failed for meeting. That is an
injustice and it is the failure mode that ends an evaluator's credibility. A false
negative is a test that does not exist: real cost, no injustice. So precision is gated at
95%, high-materiality precision at 98%, recall at 80%, and an F1 is reported but never
gated on.

**The interval's lower bound is compared, not the point estimate.** Precision of 100% over
sixty facts has a Wilson lower bound near 94% and does not clear the 98% bar. That is a
statement about how much reading an annotator has to do, and it is better to know it
before commissioning the work than after.

**A self-marked annotation never clears a build.** An annotation written by whoever wrote
the extraction prompts measures agreement with the pipeline's own assumptions. Two people
who share an assumption agree perfectly and are wrong together, and the disagreements
about what a document *means* — precisely where an extraction pipeline fails — are exactly
what such a measurement cannot see. Nothing in code can verify who wrote what, so the gold
file declares it, `trustworthy` is `False` whenever it is absent or false, and the
declaration is printed beside every number it produced.

**Coverage bounds the claim.** Scoring runs over the relations the annotation covers, not
the whole schema. A relation nobody annotated is neither right nor wrong, and counting the
graph's unannotated relations as inventions would make the score a function of how much
someone had time to read.

**Strict and relaxed are both reported.** Strict requires the same relation between the
same two entities by content hash — what the graph contains and what a contract resolves
from. Relaxed ignores what the *subject* was named, requiring only the same type. The gap
between them is the diagnostic.

---

## 3. The first measurement

Twenty-three facts annotated from §§3–6 of the card-authentication policy.

```
strict   precision 70% [49%, 84%]   recall 70% [49%, 84%]   F1 0.70
relaxed  precision 75%              recall 79%
high     precision 67%              recall 80%     over 15 facts that can fail an agent
spans    88% of agreed facts cite the same sentence the annotator did

UNDER GATE: high-materiality precision 67% (lower bound 44%) is under the 98% gate
UNDER GATE: precision 70% (lower bound 49%) is under the 95% gate
UNDER GATE: recall 70% (lower bound 49%) is under the 80% gate
```

**Three gates, three failures.** This is the honest state of the extraction, and every
other number in this repository — 32 bases, 410 planned runs, a pseudo-R² of 0.87 — sits
on top of it.

### What the disagreements actually are

Not one number but four different problems, which is why the defect list matters more than
the score:

**Naming (2).** The policy labels a rule **No servicing**; the pipeline named the node
after the sentence it appears in. The fact was read correctly. This is what relaxed scoring
separates out, and it is a canonicalisation problem, not an extraction one.

**Threshold attachment (3).** "Enforce a hard maximum of 3 authentication attempts" was
attached to three different subjects — the retry decision, the attempt counter, and a
sentence-named rule — where the annotator put it on one. The pipeline over-generates rather
than choosing, and three near-duplicate `count_limit` assertions is a real defect: a
reviewer sees the same limit three times and cannot tell which is authoritative.

**Over-reading (2).** "Only tell the customer that authentication succeeded when
`authenticate_customer` returns `AUTHENTICATED`" became `RULE_REQUIRES AUTHENTICATED`. That
is a conditional constraint on a *turn*, not a requirement that an outcome occur.

**Recall (4).** §3A's "Call `authenticate_customer`" was not attached to the opening state,
and three of the four fixed utterances in §6 were not linked to their Turn. The wording is
in the graph; the Turn that must say it is not. Those are the tests that quietly do not
exist.

### The gate found an error in its own gold set

The first run scored `transfer_to_ccp RETURNS FAILED` as an invention. The tool table reads
`TRANSFERRED / FAILED` — the pipeline was right and the annotation was wrong. It is
corrected, with a note in the file saying why.

That is the most useful thing an annotation can be wrong about, and it is the argument for
printing every disagreement rather than only the score. A gate that reported "70%" and
nothing else would have sent someone to fix a pipeline that was correct.

---

## 4. Where it sits in the product

`metric accuracy` runs it. The **overview page leads with it**, above build identity,
because it is the number the others depend on; a build with no annotation says so in as
many words rather than leaving the panel out. `accuracy.json` carries the full defect list.
`metric accuracy --strict` exits non-zero unless the gate clears on an independent reading,
which is the CI shape.

---

## 5. Limits

- **The shipped annotation is not independent**, and the gate says so on every surface it
  appears. It demonstrates the machinery and measures whether the pipeline reads the
  document the way its prompt author intended. That is worth knowing and it is not an
  accuracy gate.
- **Twenty-three facts is a small sample.** The intervals are wide — ±18 points — so the
  point estimates should not be quoted without them. A 98% high-materiality bar needs
  several hundred annotated facts to clear at all.
- **One corpus, one annotator.** No inter-annotator agreement, so how much of the
  disagreement is genuine ambiguity in the policy rather than pipeline error is unmeasured.
  Two independent readings of the same section would answer that and would also calibrate
  how strict the gates can reasonably be.
- **The flowchart is not scored.** §8 of the policy carries the same workflow as a diagram,
  and the document's own claim is that the two readings should agree. The transcription
  does not reproduce the image, so the check the corpus was chosen for cannot be run.
- **Relaxed scoring is a real weakening.** Two distinct rules of the same type are
  conflated by it. It is reported beside the strict score, never instead of it.

---

## 6. Next

1. **Commission an independent annotation** of the same four sections, from someone who has
   not seen the prompts. This is now a data task, and it is the highest-value item left.
2. **A second annotator on the same sections**, for inter-annotator agreement — the number
   that says how much of the 30% gap is ambiguity rather than error.
3. **Fix the four defect classes above**, in the order recall, threshold attachment,
   over-reading, naming. Recall first because a missing test is invisible, and naming last
   because relaxed scoring shows it costs nothing but legibility.
4. Re-run the gate after each, and keep the score in the build report so the trend is
   visible rather than rediscovered.
