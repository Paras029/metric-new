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

from collections.abc import Iterable, Mapping, Sequence

from metric.ontology.ids import question_id
from metric.ontology.types import Span, Triple, TripleStatus

REVIEW_QUESTION = "review/unwitnessed"


def review_question_id(triple: Triple) -> str:
    """The id of the question that asks a person to confirm this triple."""
    return question_id(REVIEW_QUESTION, *triple.key)


def merge(triples: Iterable[Triple]) -> list[Triple]:
    """Collapse triples sharing a key, unioning spans and methods."""
    grouped: dict[tuple[str, str, str], list[Triple]] = {}
    for triple in triples:
        grouped.setdefault(triple.key, []).append(triple)
    return [_merged(group) for _, group in sorted(grouped.items())]


def apply_witness_bar(
    triples: Sequence[Triple],
    *,
    approved: Mapping[str, str] | None = None,
    enabled: bool = True,
    materiality: str = "high",
    min_passages: int = 2,
) -> list[Triple]:
    """Move unsupported high-materiality triples to `review`, unless a person has ruled.

    A recorded decision outranks the bar in both directions: an approved triple is
    admitted and can block, a rejected one leaves the graph. That is the loop closing
    — the bar is a queue, not a verdict, and without somewhere for the answer to land
    a single-source policy would produce a graph that can never block anything.
    """
    ruled = approved or {}
    return [
        _bar(triple, ruled, enabled=enabled, materiality=materiality, min_passages=min_passages)
        for triple in triples
    ]


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


def _bar(
    triple: Triple,
    ruled: Mapping[str, str],
    *,
    enabled: bool,
    materiality: str,
    min_passages: int,
) -> Triple:
    if triple.status != "admitted":
        return triple

    answer = ruled.get(review_question_id(triple), "")
    if answer == "reject":
        return _with_status(triple, "rejected")
    if answer == "approve":
        return triple
    if not enabled or triple.materiality != materiality or triple.methods != {"llm"}:
        return triple
    if len({span.passage_id for span in triple.spans}) >= min_passages:
        return triple
    return _with_status(triple, "review")


def _with_status(triple: Triple, status: TripleStatus) -> Triple:
    return Triple(
        head=triple.head,
        relation=triple.relation,
        tail=triple.tail,
        tail_kind=triple.tail_kind,
        spans=triple.spans,
        methods=triple.methods,
        materiality=triple.materiality,
        status=status,
    )
