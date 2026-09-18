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
from metric.reconcile.dedup import apply_witness_bar, merge


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
) -> Reconciled:
    merged = apply_witness_bar(merge(triples))

    # Labels come from a provisional graph: conflict messages name entities the way the
    # corpus does, which is the only form a reviewer can act on.
    provisional = build(entities, merged)
    found = conflicts.detect(merged, schema=schema, label=provisional.label)
    resolution = conflicts.resolve(merged, found, effective_dates=effective_dates)

    graph = build(entities, resolution.triples)
    questions = (*resolution.questions, *integrity.check(graph))

    return Reconciled(
        graph=graph,
        questions=tuple(sorted(questions, key=lambda q: (q.kind, q.id))),
        conflicts=tuple(found),
    )
