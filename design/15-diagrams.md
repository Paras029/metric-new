# Design Plan 15 — Reading the workflow off the picture

A workflow diagram is not an illustration of the operating procedure. In most packs it
*is* the operating procedure, and the prose is the commentary. The card-authentication
policy says so about itself: "the workflow backbone should be recoverable from the diagram
as well as from §3, and the two readings agreeing is itself a useful check."

Until now this repository could not read one.

---

## 1. What was there

A stub. `read_document` on a `.png` returned a block whose **text was the file path**:

```python
RawBlock(location=f"{label}:image", kind="image", text=str(path))
```

That path then went through batching, extraction and admission like any other prose. The
best case was that it produced nothing; there was no case where it produced the workflow.

---

## 2. Three passes, and why it is three

**One image at a time.** Each picture is read alone, into an explicit list of boxes and
arrows — enumerated, not described. A model given eight tiles at once summarises; given
one, it counts. And enumeration is what makes a miss visible: a box that was skipped shows
up as an arrow pointing at nothing, where a box left out of a paragraph simply vanishes.

**Then the join.** One pass sees every reading together and follows an arrow that ran off
the edge of one picture into the picture that picks it up. This is the whole answer to *a
diagram too long for one page*: the tiles go in the order a person would look at them, each
box keeps the id its own page gave it, and the join is a question about which ids are the
same box. A box appearing twice — once real, once as a stub showing where the previous
page's arrow arrives — is exactly what it is asked to reconcile.

**Then the repair.** The audit says what the joined graph cannot account for, and those
findings go back **with the pictures still attached**. Not "read it again, better", which
returns a differently-wrong answer, but a list of specific holes: *D2 outcome "FAILED" leads
nowhere; no state declares itself reached_via D2=FAILED. Follow that arrow and say where it
lands, or say it leaves the page.*

The audit is the load-bearing part, and every check in it is a property the graph needs to
be **walkable** — not an opinion about how the workflow should have been drawn:

| | |
|---|---|
| no state marked `Start` | nothing to walk from |
| a decision with fewer than two outcomes | not a branch |
| an outcome no state is reached by | an arrow whose destination went unrecorded |
| `reached_via` naming a decision that does not exist | one of the two ids is wrong |
| a `continues` nothing picks up | an arrow off the page with no other page catching it |
| a state nothing leads to | unreachable, or an arrow in was missed |

**A repair never removes.** A second look that came back quieter is a worse reading, not a
correction, and letting it delete the first reading's boxes is how a repair pass makes the
graph smaller every time it runs. It replaces what it names and adds what it did not have.
A repair that fixes nothing stops rather than looping.

---

## 3. Provenance, when there are no sentences

Every fact in this graph names the passage and the characters it came from, and the UI is
built so a reviewer clicks a claim and reads the sentence behind it. A picture has no
sentences.

So the reading becomes one. Each image gets a passage whose text is **what was read off
it**, one fact per line:

```
box: Authentication attempts — reached via D1=proceed — calls authenticate_customer
diamond: authentication result — FAILED, AUTHENTICATED
arrow: FAILED — authentication result → Failed authentication and retry
```

and every triple cites the line that carries it. Nothing goes around the admission gate:
the quote has to be locatable in the passage exactly as a prose quote does. What a reviewer
sees is what was *seen*, not what the picture "means".

**Only the structural relations.** A drawing shows where the journey goes and what branches
it. It does not state what a rule requires or what wording is fixed, and reading those off a
picture would be the one thing this pipeline exists to refuse. The candidates are limited to
`STARTS_AT`, `HAS_NEXT_STEP`, `OFFERS_DECISION`, `HAS_OUTCOME`, `LEADS_TO`, `IS_TERMINAL`
and `USES_TOOL`, and a test asserts no `RULE_*` can come out of it.

---

## 4. The payoff: two readings are two witnesses

The witness bar holds any high-materiality fact resting on a single model reading. A
diagram-read fact is marked `vision`; a prose-read one is `llm`. Measured:

```
prose alone   -> review      (one witness, a person must approve it)
prose + vision -> admitted   (two independent readings agree)
```

That is the check the corpus document asked for, made real. It also means adding the
flowchart to a corpus does not merely add facts — it *promotes* facts the prose already
carried, and shortens the review queue for the right reason rather than by lowering a bar.

---

## 5. Getting the picture there

Two things that are cheap here and expensive later.

**Order.** A long workflow is exported as `flow-1.png` … `flow-10.png`, and a string sort
puts 10 before 2. The join is told to rely on page order, so the sort is on the digits.

**Size.** A scanned A3 workflow is routinely 6000px and several megabytes, and the API
refuses it. Refusing per-call, after the text has already been read, is the worst place to
find out — so an oversized image is reduced once, up front, and **the reduction is
reported**: a diagram read at half resolution may have lost its smallest arrow labels, and
that belongs in the output rather than hidden.

Pillow does the reducing and is optional (`metric[image]`). Without it an oversized image
is refused with its size and what to do about it.

**One bad tile does not lose the others.** A pack of eight with one truncated file gives
seven tiles of workflow and a note naming the eighth. Writing the test for that found a real
bug: a corrupt file raised an unhandled Pillow exception straight through `load_all`,
killing the build over exactly the input most likely to be scanned badly.

---

## 6. Limits

- **Not run against a live model here.** There is no API key in this environment, so every
  pass is exercised against a scripted vision gateway and the real question — how well a
  model enumerates a dense flowchart, and whether the join actually finds the right box
  across a page break — is unmeasured. The structure, audit, repair, provenance and image
  handling are all tested; the reading itself is not.
- **The connector convention is guessed.** `continues` carries whatever the off-page
  connector says, and the join is told to match it. Real packs use circled letters, page
  references, or nothing at all, and which of those a model handles is unknown.
- **A diagram cannot contradict the prose.** Where the two readings disagree, both facts
  enter and the existing conflict machinery reports it. That is right, but a *diagram*
  disagreeing with prose is a specific and interesting event and deserves its own question
  rather than a generic conflict.
- **Nothing reads a diagram embedded in a PDF or a slide.** Only standalone image files.
  A flowchart on page 9 of a PDF is still invisible.

---

## 7. Next

1. **Run it against a real flowchart** — the first thing, and it needs a key.
2. **Extract embedded images** from PDFs and slide decks, which is where most real
   workflow diagrams actually live.
3. **A prose/diagram disagreement question**, distinct from a generic conflict.
