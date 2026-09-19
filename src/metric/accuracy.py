"""Is the graph right? Measured against a human reading of the same source.

Everything in this repository rests on the extraction being correct, and until now
nothing measured that. The bases come from the graph. The contracts come from the graph.
An agent is failed against the graph. A fact the pipeline invents becomes a test someone
is failed for, and no amount of provenance, capability gating or answer recovery detects
an error that was in the source reading itself — every one of those checks confirms the
graph is internally consistent, which a confidently wrong graph also is.

So: a person reads the corpus, writes down the triples that are in it, and the pipeline's
output is compared against that.

**Precision and recall are not interchangeable here, and the gate treats them
differently.** A false positive is a fact the pipeline invented, and it becomes an
expectation an agent is failed for meeting — an injustice, and the failure mode that
destroys trust in an evaluator. A false negative is a test that does not exist: real
cost, no injustice. So precision carries the higher bar, high-materiality relations carry
a higher bar still, and the two numbers are never averaged into one.

**Independence is declared, not verified.** An annotation written by whoever wrote the
extraction prompts measures agreement with itself. Nothing in code can check that, so the
gold file must say who annotated it and whether they wrote the prompts, and that
declaration is printed beside every number it produced. A measurement whose independence
is unstated is reported as `not independent` rather than given the benefit of the doubt.

**Coverage bounds the claim.** Precision over three of forty passages is precision over
three passages. The report says which were annotated and refuses to generalise past them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from metric.attribution import Interval, wilson
from metric.graph.model import Graph
from metric.ontology.canonical import canonical_surface
from metric.ontology.ids import canonical_name, entity_id
from metric.ontology.schema import Schema

# What a build has to reach before its graph may block an agent. Precision is stricter
# than recall for the reason in the module docstring, and high-materiality relations are
# stricter still because those are the ones that can fail somebody.
DEFAULT_GATE: dict[str, float] = {
    "precision": 0.95,
    "precision_high": 0.98,
    "recall": 0.80,
}


class AnnotationError(Exception):
    """Raised when a gold-standard file is malformed."""


@dataclass(frozen=True, slots=True)
class GoldTriple:
    """One fact a person says is in the source."""

    head: str
    relation: str
    tail: str
    head_type: str
    tail_type: str
    quote: str = ""
    note: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.head, self.relation, self.tail)

    def as_dict(self) -> dict[str, Any]:
        return {
            "head": self.head,
            "relation": self.relation,
            "tail": self.tail,
            "quote": self.quote,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class Annotation:
    """A gold standard, and everything needed to judge how far it can be trusted."""

    corpus: str
    annotator: str
    independent: bool
    triples: tuple[GoldTriple, ...]
    covers: tuple[str, ...] = ()
    note: str = ""

    @property
    def relations(self) -> frozenset[str]:
        return frozenset(t.relation for t in self.triples)

    def as_dict(self) -> dict[str, Any]:
        return {
            "corpus": self.corpus,
            "annotator": self.annotator,
            "independent": self.independent,
            "covers": list(self.covers),
            "note": self.note,
            "triples": [t.as_dict() for t in self.triples],
        }


@dataclass(frozen=True, slots=True)
class Score:
    true_positive: int
    false_positive: int
    false_negative: int

    @property
    def predicted(self) -> int:
        return self.true_positive + self.false_positive

    @property
    def actual(self) -> int:
        return self.true_positive + self.false_negative

    @property
    def precision(self) -> float:
        return self.true_positive / self.predicted if self.predicted else 0.0

    @property
    def recall(self) -> float:
        return self.true_positive / self.actual if self.actual else 0.0

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0

    @property
    def precision_interval(self) -> Interval:
        return wilson(self.true_positive, self.predicted)

    @property
    def recall_interval(self) -> Interval:
        return wilson(self.true_positive, self.actual)

    def as_dict(self) -> dict[str, Any]:
        return {
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
            "precision": self.precision,
            "precision_interval": self.precision_interval.as_dict(),
            "recall": self.recall,
            "recall_interval": self.recall_interval.as_dict(),
            "f1": self.f1,
        }


@dataclass(frozen=True, slots=True)
class Accuracy:
    """Three scores, because they answer three different questions.

    `overall` is strict: the same relation between the same two entities, by content
    hash. That is what the graph actually contains and what a contract is resolved from,
    so it is the one the gate runs on.

    `relaxed` ignores what the *subject* was named, requiring only that it be the same
    kind of thing. The first run of this gate scored 65% strict and the difference was
    almost entirely a rule the policy labels **Retry control** and the pipeline named
    after the sentence it appears in. The fact was read correctly; the node has a
    different name. Reporting only the strict number would have sent someone to fix an
    extractor that was working.

    `naming` lists exactly those cases, which is the diagnostic: a large gap between
    strict and relaxed means fix canonicalisation, a small one means fix the reading.
    """

    overall: Score
    relaxed: Score
    by_relation: dict[str, Score]
    high_materiality: Score
    invented: tuple[tuple[str, str, str], ...]
    missed: tuple[tuple[str, str, str], ...]
    near_misses: tuple[str, ...]
    naming: tuple[str, ...]
    span_agreement: Score
    annotation: Annotation
    gate: dict[str, float]
    notes: tuple[str, ...]

    @property
    def failures(self) -> tuple[str, ...]:
        """Which thresholds this build is under, worst case first.

        The interval's lower bound is compared, not the point estimate. A precision of
        1.00 over six triples has a lower bound near 0.6, and passing a 0.95 gate on six
        observations is not evidence of anything.
        """
        found: list[str] = []
        if self.high_materiality.predicted:
            low = self.high_materiality.precision_interval.low
            if low < self.gate["precision_high"]:
                found.append(
                    f"high-materiality precision {self.high_materiality.precision:.0%} "
                    f"(lower bound {low:.0%}) is under the {self.gate['precision_high']:.0%} "
                    "gate — these are the facts that can fail an agent"
                )
        if self.overall.predicted:
            low = self.overall.precision_interval.low
            if low < self.gate["precision"]:
                found.append(
                    f"precision {self.overall.precision:.0%} (lower bound {low:.0%}) is "
                    f"under the {self.gate['precision']:.0%} gate"
                )
        if self.overall.actual:
            low = self.overall.recall_interval.low
            if low < self.gate["recall"]:
                found.append(
                    f"recall {self.overall.recall:.0%} (lower bound {low:.0%}) is under "
                    f"the {self.gate['recall']:.0%} gate"
                )
        return tuple(found)

    @property
    def trustworthy(self) -> bool:
        """Whether this measurement may be used to clear a build at all.

        An annotation by whoever wrote the prompts measures agreement with itself. It is
        worth having — it catches outright breakage — and it is not an accuracy gate, so
        it never returns `True` here however good the numbers are.
        """
        return self.annotation.independent and not self.failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall.as_dict(),
            "relaxed": self.relaxed.as_dict(),
            "high_materiality": self.high_materiality.as_dict(),
            "by_relation": {k: v.as_dict() for k, v in sorted(self.by_relation.items())},
            "span_agreement": self.span_agreement.as_dict(),
            "invented": [list(t) for t in self.invented],
            "missed": [list(t) for t in self.missed],
            "near_misses": list(self.near_misses),
            "naming": list(self.naming),
            "annotation": self.annotation.as_dict(),
            "gate": dict(self.gate),
            "failures": list(self.failures),
            "trustworthy": self.trustworthy,
            "notes": list(self.notes),
        }


def load_annotation(path: Path) -> Annotation:
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    if not isinstance(document, dict):
        raise AnnotationError(f"{path} does not contain a YAML mapping")

    for required in ("corpus", "annotator", "independent"):
        if required not in document:
            raise AnnotationError(
                f"{path} is missing {required!r}. A measurement whose provenance is "
                "unstated cannot clear a build"
            )

    triples = tuple(
        _gold(raw, path, index)
        for index, raw in enumerate(document.get("triples") or ())
    )
    if not triples:
        raise AnnotationError(f"{path} annotates no triples")

    return Annotation(
        corpus=str(document["corpus"]),
        annotator=str(document["annotator"]),
        independent=bool(document["independent"]),
        triples=triples,
        covers=tuple(str(c) for c in document.get("covers") or ()),
        note=str(document.get("note", "")),
    )


def _gold(raw: Any, path: Path, index: int) -> GoldTriple:
    if not isinstance(raw, dict):
        raise AnnotationError(f"{path}: every triple must be a mapping")
    try:
        head, head_type = _entity(raw["head"], path, index, "head")
        tail_raw = raw["tail"]
        relation = str(raw["relation"])
    except KeyError as exc:
        raise AnnotationError(f"{path}: triple {index} is missing {exc.args[0]!r}") from exc

    if isinstance(tail_raw, dict):
        tail, tail_type = _entity(tail_raw, path, index, "tail")
    else:
        tail, tail_type = str(tail_raw), "literal"

    return GoldTriple(
        head=head,
        relation=relation,
        tail=tail,
        head_type=head_type,
        tail_type=tail_type,
        quote=str(raw.get("quote", "")),
        note=str(raw.get("note", "")),
    )


def _entity(raw: Any, path: Path, index: int, side: str) -> tuple[str, str]:
    if not isinstance(raw, dict) or "type" not in raw or "name" not in raw:
        raise AnnotationError(
            f"{path}: triple {index}'s {side} must be a mapping with `type` and `name`"
        )
    return str(raw["name"]), str(raw["type"])


def measure(
    graph: Graph,
    schema: Schema,
    annotation: Annotation,
    *,
    gate: dict[str, float] | None = None,
) -> Accuracy:
    """Compare the built graph against a human reading of the same source."""
    thresholds = {**DEFAULT_GATE, **(gate or {})}
    notes: list[str] = []

    gold: dict[tuple[str, str, str], GoldTriple] = {}
    for triple in annotation.triples:
        if triple.relation not in schema.relations:
            notes.append(
                f"the annotation uses {triple.relation}, which this schema does not "
                "define; it was left out of the comparison"
            )
            continue
        gold[_resolve(triple)] = triple

    scope = annotation.relations & set(schema.relations)
    predicted = {(t.head, t.relation, t.tail) for t in graph.live if t.relation in scope}
    if scope != set(schema.relations):
        notes.append(
            f"scored over the {len(scope)} relations the annotation covers, not all "
            f"{len(schema.relations)} in the schema — a relation nobody annotated is "
            "neither right nor wrong here"
        )

    keys = set(gold)
    overall = _score(predicted, keys)

    by_relation: dict[str, Score] = {}
    for relation in sorted(scope):
        by_relation[relation] = _score(
            {t for t in predicted if t[1] == relation}, {k for k in keys if k[1] == relation}
        )

    high = {r for r in scope if schema.relations[r].materiality == "high"}
    high_score = _score(
        {t for t in predicted if t[1] in high}, {k for k in keys if k[1] in high}
    )
    if not high:
        notes.append(
            "the annotation covers no high-materiality relation, so the gate that "
            "matters most was not exercised"
        )

    relaxed, naming = _relaxed(graph, predicted, keys)
    if naming:
        notes.append(
            f"{len(naming)} facts were read correctly but under a different name for the "
            "subject; relaxed precision and recall are the numbers to read alongside those"
        )

    return Accuracy(
        overall=overall,
        relaxed=relaxed,
        naming=naming,
        by_relation=by_relation,
        high_materiality=high_score,
        invented=tuple(sorted(_label(graph, t) for t in predicted - keys)),
        missed=tuple(sorted(_annotated(gold[k]) for k in keys - predicted)),
        near_misses=_near_misses(graph, predicted, keys),
        span_agreement=_spans(graph, gold, predicted & keys),
        annotation=annotation,
        gate=thresholds,
        notes=tuple(notes),
    )


def _resolve(triple: GoldTriple) -> tuple[str, str, str]:
    """A gold triple in the pipeline's own identity scheme.

    Deliberately the same canonicalisation the pipeline uses. Resolving the two sides
    differently would measure string normalisation rather than extraction, and would
    report a disagreement about capitalisation as a fabricated fact.
    """
    head = entity_id(triple.head_type, canonical_surface(triple.head_type, triple.head))
    if triple.tail_type == "literal":
        return (head, triple.relation, triple.tail)
    tail = entity_id(triple.tail_type, canonical_surface(triple.tail_type, triple.tail))
    return (head, triple.relation, tail)


def _score(predicted: set[tuple[str, str, str]], gold: set[tuple[str, str, str]]) -> Score:
    return Score(
        true_positive=len(predicted & gold),
        false_positive=len(predicted - gold),
        false_negative=len(gold - predicted),
    )


def _relaxed(
    graph: Graph, predicted: set[tuple[str, str, str]], gold: set[tuple[str, str, str]]
) -> tuple[Score, tuple[str, ...]]:
    """Score again, ignoring what the subject was called.

    A triple is credited when the same relation holds to the same object from a subject
    of the same type. That is a real weakening — two different rules of the same type
    would be conflated — so it is reported beside the strict score rather than instead of
    it, and every case it rescues is listed.
    """

    def loosen(triple: tuple[str, str, str]) -> tuple[str, str, str]:
        head, relation, tail = triple
        entity = graph.entity(head)
        return (entity.type if entity else head.split(":")[0], relation, tail)

    loose_predicted = {loosen(t) for t in predicted}
    loose_gold = {loosen(t) for t in gold}

    rescued = sorted(
        f"{graph.label(head)} {relation} {graph.label(tail)}"
        for head, relation, tail in (predicted - gold)
        if loosen((head, relation, tail)) in loose_gold
    )
    return _score(loose_predicted, loose_gold), tuple(rescued)


def _near_misses(
    graph: Graph, predicted: set[tuple[str, str, str]], gold: set[tuple[str, str, str]]
) -> tuple[str, ...]:
    """Right subject and relation, wrong object.

    Worth separating from an invention: it means the pipeline found the sentence and read
    it, and got the object wrong. That is a prompt or schema problem, and it is fixable in
    a way a hallucinated subject is not.
    """
    by_head: dict[tuple[str, str], set[str]] = {}
    for head, relation, tail in gold:
        by_head.setdefault((head, relation), set()).add(tail)

    found: list[str] = []
    for head, relation, tail in sorted(predicted - gold):
        expected = by_head.get((head, relation))
        if expected:
            found.append(
                f"{graph.label(head)} {relation} {graph.label(tail)} "
                f"— annotated as {', '.join(sorted(graph.label(e) for e in expected))}"
            )
    return tuple(found)


def _spans(
    graph: Graph,
    gold: dict[tuple[str, str, str], GoldTriple],
    agreed: set[tuple[str, str, str]],
) -> Score:
    """Of the facts both found, did they cite the same sentence?

    A right fact cited to the wrong sentence is still a defect: the provenance is what a
    reviewer follows, and following it to a sentence that does not say the thing is how
    a reviewer stops trusting every citation.
    """
    matched = 0
    mismatched = 0
    for key in agreed:
        quote = gold[key].quote.strip()
        if not quote:
            continue
        cited = [
            span.quote
            for t in graph.live
            if (t.head, t.relation, t.tail) == key
            for span in t.spans
        ]
        if any(_folded(quote) in _folded(c) or _folded(c) in _folded(quote) for c in cited):
            matched += 1
        else:
            mismatched += 1
    return Score(true_positive=matched, false_positive=mismatched, false_negative=0)


def _label(graph: Graph, triple: tuple[str, str, str]) -> tuple[str, str, str]:
    head, relation, tail = triple
    return (graph.label(head), relation, graph.label(tail))


def _annotated(triple: GoldTriple) -> tuple[str, str, str]:
    """A missed fact is not in the graph, so the graph cannot name it.

    Printing its content hash instead sends a reader looking for an entity that does not
    exist. The annotator's own words are what they need.
    """
    return (triple.head, triple.relation, triple.tail)


def _folded(text: str) -> str:
    return " ".join(canonical_name(text).split())
