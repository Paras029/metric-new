"""The admission gate.

A candidate is a proposal; a triple is what survived. Criteria run in a fixed order,
cheapest and most decisive first, and the first failure is what gets recorded — a
candidate with a malformed relation is not worth locating a quote for, and a
rejection listing four reasons tells you less than one listing the first.

Nothing fails silently. Every rejected candidate lands in quarantine with the
criterion it failed and the quote it claimed, which is what makes a broken extractor
findable rather than merely suspected.

The materiality bar is not here. It asks whether a triple has a second witness, and
a witness may live in another passage or another document, so it can only be
evaluated after duplicates have merged. It runs in `reconcile`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from metric.admit.grounding import Location, locate, normalised
from metric.ontology.canonical import NUMBER_WORDS, as_number, canonical_surface
from metric.ontology.ids import entity_id
from metric.ontology.schema import RelationSpec, Schema
from metric.ontology.types import (
    Candidate,
    Entity,
    Passage,
    Rejection,
    Span,
    TailKind,
    Triple,
)

# Modal negation: what a prohibition is actually built from. Kept narrow on purpose --
# a bare "not" appears in plenty of sentences that state a requirement, and rejecting
# those would cost more in lost facts than the flips it would catch.
_MODAL_NEGATION = re.compile(
    r"\b(?:must not|may not|shall not|should not|cannot|can not|must never|may never|"
    r"is not permitted|are not permitted|is prohibited|are prohibited|is forbidden|"
    r"are forbidden|do not|does not|never)\b",
    re.IGNORECASE,
)
# Any negation at all: enough to believe a prohibition was stated.
_ANY_NEGATION = re.compile(
    r"\b(?:no|not|never|without|prohibit(?:s|ed)?|forbid(?:s|den)?|disallow(?:s|ed)?|"
    r"refrain|avoid|decline|refuse)\b|n't\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Admission:
    triples: tuple[Triple, ...]
    rejections: tuple[Rejection, ...]
    entities: tuple[Entity, ...]


def admit(
    candidates: Sequence[Candidate],
    *,
    schema: Schema,
    passages: Mapping[str, Passage],
) -> Admission:
    triples: list[Triple] = []
    rejections: list[Rejection] = []
    surfaces: dict[tuple[str, str], set[str]] = {}

    for candidate in candidates:
        location, rejection = _check(candidate, schema=schema, passages=passages)
        if rejection is not None or location is None:
            rejections.append(
                rejection
                or Rejection(candidate=candidate, criterion="quote", detail="quote not located")
            )
            continue

        passage = passages[candidate.passage_id]
        spec = schema.relations[candidate.relation]
        head_canonical = canonical_surface(candidate.head_type, candidate.head)
        head = entity_id(candidate.head_type, head_canonical)
        surfaces.setdefault((candidate.head_type, head_canonical), set()).add(candidate.head)

        tail: str
        tail_kind: TailKind
        if spec.takes_literal:
            tail, tail_kind = candidate.tail, "literal"
        else:
            tail_canonical = canonical_surface(candidate.tail_type, candidate.tail)
            tail, tail_kind = entity_id(candidate.tail_type, tail_canonical), "entity"
            surfaces.setdefault((candidate.tail_type, tail_canonical), set()).add(candidate.tail)

        triples.append(
            Triple(
                head=head,
                relation=candidate.relation,
                tail=tail,
                tail_kind=tail_kind,
                spans=(
                    Span(
                        passage_id=passage.id,
                        start=location.start,
                        end=location.end,
                        quote=location.text,
                    ),
                ),
                methods=frozenset({candidate.method}),
                materiality=spec.materiality,
            )
        )

    entities = tuple(
        Entity(
            id=entity_id(entity_type, canonical),
            type=entity_type,
            canonical=canonical,
            surfaces=frozenset(forms),
        )
        for (entity_type, canonical), forms in sorted(surfaces.items())
    )
    return Admission(triples=tuple(triples), rejections=tuple(rejections), entities=entities)


def _check(
    candidate: Candidate,
    *,
    schema: Schema,
    passages: Mapping[str, Passage],
) -> tuple[Location | None, Rejection | None]:
    """Run the criteria in order, returning the located span or the first failure."""
    problem = schema.check(candidate)
    if problem is not None:
        return None, Rejection(candidate=candidate, criterion="schema", detail=problem)

    if not candidate.head or not candidate.tail:
        return None, Rejection(
            candidate=candidate, criterion="schema", detail="head or tail is empty"
        )

    passage = passages.get(candidate.passage_id)
    if passage is None:
        return None, Rejection(
            candidate=candidate,
            criterion="citation",
            detail=f"unknown passage {candidate.passage_id!r}",
        )

    location = locate(candidate.quote, passage.text)
    if location is None:
        return None, Rejection(
            candidate=candidate,
            criterion="quote",
            detail=f"quote not found in passage {passage.location}",
        )

    spec = schema.relations[candidate.relation]
    mismatch = _polarity_problem(spec, location.text)
    if mismatch is not None:
        return None, Rejection(candidate=candidate, criterion="polarity", detail=mismatch)

    missing = _value_problem(spec, candidate.tail, location.text)
    if missing is not None:
        return None, Rejection(candidate=candidate, criterion="value", detail=missing)

    return location, None


def _polarity_problem(spec: RelationSpec, quote: str) -> str | None:
    """Check the quote's negation against the relation's declared polarity.

    A requirement extracted as a prohibition, or the reverse, is the one extraction
    error that produces a confidently wrong test rather than a missing one, and it is
    invisible to every other check here.
    """
    if spec.polarity == "positive" and _MODAL_NEGATION.search(quote):
        return f"{spec.name} is a positive relation but the quote states a prohibition"
    if spec.polarity == "negative" and not _ANY_NEGATION.search(quote):
        return f"{spec.name} is a prohibition but the quote contains no negation"
    return None


def _value_problem(spec: RelationSpec, tail: str, quote: str) -> str | None:
    """For a verbatim literal, require the value to be in the cited span.

    Enum and boolean tails are the pipeline's own vocabulary rather than the source's,
    so they are exempt; a free-text literal is a claim about the source's own words
    and has to be visible in them.

    The one relaxation is numeric: a source writing "three" supports a value of 3, and
    holding the digit form against it would drop a fact over spelling. The comparison
    is still on the value, not on similarity — nothing but an exact numeric equality
    gets through this way.
    """
    if not spec.takes_literal or spec.literal_type != "str":
        return None
    if normalised(tail) in normalised(quote):
        return None

    number = as_number(tail)
    spelled = NUMBER_WORDS.get(number) if number is not None else None
    if spelled and re.search(rf"\b{spelled}\b", quote, re.IGNORECASE):
        return None

    return f"{spec.name} claims a value the cited quote does not contain"
