"""Merging restatements, and the witness bar that depends on it.

A document states the same fact in several places, and the pipeline reads
overlapping batches on purpose, so the same triple arrives more than once by design.
Merging keeps every citation: one fact stated three ways is one triple with three
spans, not three triples or one with two citations thrown away.

The witness bar runs here rather than in the gate because it asks a question no
single candidate can answer. A high-materiality triple — a transition, a threshold, a
prohibition — is admitted on a deterministic origin or on support from more than one
passage. A model-only claim supported by exactly one sentence goes to review. That is
v1's substitute for an entailment check: instead of judging whether the quote implies
the claim with a second unvalidated model, the claims that would hurt most if wrong
are the ones a person sees.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from metric.ontology.types import Span, Triple


def merge(triples: Iterable[Triple]) -> list[Triple]:
    """Collapse triples sharing a key, unioning spans and methods."""
    grouped: dict[tuple[str, str, str], list[Triple]] = {}
    for triple in triples:
        grouped.setdefault(triple.key, []).append(triple)
    return [_merged(group) for _, group in sorted(grouped.items())]


def apply_witness_bar(triples: Sequence[Triple]) -> list[Triple]:
    """Move unsupported high-materiality triples to `review`.

    Leaves every other status alone: a triple already marked conflicted or superseded
    has been decided on stronger grounds than this.
    """
    return [_bar(triple) for triple in triples]


def _merged(group: list[Triple]) -> Triple:
    first = group[0]
    spans: dict[tuple[str, int, int], Span] = {}
    methods: set[str] = set()
    materiality = "normal"

    for triple in group:
        for span in triple.spans:
            spans[(span.passage_id, span.start, span.end)] = span
        methods |= set(triple.methods)
        if triple.materiality == "high":
            materiality = "high"

    return Triple(
        head=first.head,
        relation=first.relation,
        tail=first.tail,
        tail_kind=first.tail_kind,
        spans=tuple(spans[key] for key in sorted(spans)),
        methods=frozenset(methods),  # type: ignore[arg-type]
        materiality=materiality,  # type: ignore[arg-type]
        status=first.status,
    )


def _bar(triple: Triple) -> Triple:
    if triple.status != "admitted" or triple.materiality != "high":
        return triple
    if triple.methods != {"llm"}:
        return triple
    if len({span.passage_id for span in triple.spans}) > 1:
        return triple
    return Triple(
        head=triple.head,
        relation=triple.relation,
        tail=triple.tail,
        tail_kind=triple.tail_kind,
        spans=triple.spans,
        methods=triple.methods,
        materiality=triple.materiality,
        status="review",
    )
