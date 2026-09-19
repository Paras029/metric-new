"""Reconciliation, in one ordered pass.

Order matters and is fixed: merge, then the witness bar, then conflicts, then
integrity over the resulting graph. Merging first is what stops restatements
presenting as contradictions. Conflicts run after the witness bar so that a triple
which is both unsupported and contradicted ends up marked contradicted — the
stronger fact about it.

Design plan 06 called for iterating this to a fixed point, bounded at five rounds.
It is written as a single pass instead, because nothing here feeds back: merging is
by triple key, and every later stage only assigns statuses, which no key depends on.
A second round would recompute the first round's answer. A bounded loop would have
implied a convergence that does not exist.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from metric.graph.model import Graph, build
from metric.ontology.schema import Schema
from metric.ontology.types import Entity, Question, Triple
from metric.reconcile import conflicts, integrity
from metric.reconcile.dedup import REVIEW_QUESTION, apply_witness_bar, merge, review_question_id
from metric.settings import WitnessSettings


@dataclass(frozen=True, slots=True)
class Reconciled:
    graph: Graph
    questions: tuple[Question, ...]
    conflicts: tuple[conflicts.Conflict, ...]


def reconcile(
    entities: Sequence[Entity],
    triples: Sequence[Triple],
    *,
    schema: Schema,
    effective_dates: Mapping[str, str],
    decisions: Mapping[str, str] | None = None,
    witness: WitnessSettings | None = None,
) -> Reconciled:
    bar = witness or WitnessSettings()
    merged = apply_witness_bar(
        merge(triples),
        approved=decisions,
        enabled=bar.enabled,
        materiality=bar.materiality,
        min_passages=bar.min_passages,
    )

    # Labels come from a provisional graph: conflict messages name entities the way the
    # corpus does, which is the only form a reviewer can act on.
    provisional = build(entities, merged)
    found = conflicts.detect(merged, schema=schema, label=provisional.label)
    resolution = conflicts.resolve(merged, found, effective_dates=effective_dates)

    graph = build(entities, resolution.triples)
    questions = (
        *resolution.questions,
        *integrity.check(graph),
        *_review_questions(graph),
    )

    return Reconciled(
        graph=graph,
        questions=tuple(sorted(questions, key=lambda q: (q.kind, q.id))),
        conflicts=tuple(found),
    )


def _review_questions(graph: Graph) -> tuple[Question, ...]:
    """One question per triple held for review, so the bar has somewhere to be answered.

    Without these the witness bar is a dead end: on a single-source policy almost every
    transition and threshold is a lone model reading, so almost nothing would ever be
    able to block, and nobody would be asked to change that.
    """
    return tuple(
        Question(
            id=review_question_id(triple),
            kind=REVIEW_QUESTION,
            heading=(
                f"{graph.label(triple.head)} {triple.relation} "
                f"{graph.label(triple.tail) if triple.tail_kind == 'entity' else triple.tail}"
            ),
            detail=(
                "this matters and rests on a single model reading of one passage. Approve it "
                "and it can fail an agent; reject it and it leaves the graph."
            ),
            blocks=" ".join(triple.key),
            evidence=triple.spans,
        )
        for triple in graph.triples
        if triple.status == "review"
    )
