"""Typed conflicts, and the one way they are allowed to be resolved automatically.

Every conflict here is structural — it follows from the schema or from two triples
that cannot both hold — so detection never involves a judgement call. Resolution
almost always does, and the only automatic one is declared document precedence: when
every side carries an effective date and one is strictly latest, the latest wins and
the others are marked superseded rather than deleted.

Everything else becomes a question. Picking a winner by confidence, recency of
extraction or span count would produce a graph that looks clean and quietly encodes
a coin flip, which is the failure this whole design exists to avoid.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from metric.ontology.ids import question_id
from metric.ontology.schema import Schema
from metric.ontology.types import Question, Triple


@dataclass(frozen=True, slots=True)
class Conflict:
    kind: str
    heading: str
    detail: str
    triples: tuple[Triple, ...]


@dataclass(frozen=True, slots=True)
class Resolution:
    triples: tuple[Triple, ...]
    questions: tuple[Question, ...]


def detect(
    triples: Sequence[Triple], *, schema: Schema, label: Callable[[str], str]
) -> list[Conflict]:
    live = [t for t in triples if t.status in {"admitted", "review"}]
    return [
        *_cardinality(live, schema=schema, label=label),
        *_terminal_with_successors(live, label=label),
        *_required_and_forbidden(live, label=label),
    ]


def resolve(
    triples: Sequence[Triple],
    conflicts: Sequence[Conflict],
    *,
    effective_dates: Mapping[str, str],
) -> Resolution:
    """Apply document precedence where it decides, and raise a question where it does not."""
    statuses: dict[tuple[str, str, str, str], str] = {}
    questions: list[Question] = []

    for conflict in conflicts:
        winner = _latest(conflict.triples, effective_dates)
        if winner is not None:
            for triple in conflict.triples:
                if triple is not winner:
                    statuses[_slot(triple)] = "superseded"
            continue

        for triple in conflict.triples:
            statuses[_slot(triple)] = "conflicted"
        questions.append(_question(conflict))

    updated = tuple(
        _with_status(triple, statuses[_slot(triple)]) if _slot(triple) in statuses else triple
        for triple in triples
    )
    return Resolution(triples=updated, questions=tuple(questions))


def _cardinality(
    triples: Sequence[Triple], *, schema: Schema, label: Callable[[str], str]
) -> list[Conflict]:
    grouped: dict[tuple[str, str], list[Triple]] = {}
    for triple in triples:
        spec = schema.relation(triple.relation)
        if spec is not None and spec.cardinality == "one":
            grouped.setdefault((triple.head, triple.relation), []).append(triple)

    conflicts = []
    for (head, relation), group in sorted(grouped.items()):
        tails = {t.tail for t in group}
        if len(tails) > 1:
            shown = ", ".join(sorted(label(t) for t in tails))
            conflicts.append(
                Conflict(
                    kind="cardinality",
                    heading=f"{label(head)} has more than one {relation}",
                    detail=f"{relation} admits at most one value; the corpus states: {shown}",
                    triples=tuple(group),
                )
            )
    return conflicts


def _terminal_with_successors(
    triples: Sequence[Triple], *, label: Callable[[str], str]
) -> list[Conflict]:
    terminal = {
        t.head: t for t in triples if t.relation == "IS_TERMINAL" and t.tail.lower() == "true"
    }
    successors: dict[str, list[Triple]] = {}
    for triple in triples:
        if triple.relation == "HAS_NEXT_STEP" and triple.head in terminal:
            successors.setdefault(triple.head, []).append(triple)

    return [
        Conflict(
            kind="terminal",
            heading=f"{label(head)} is terminal but has a next step",
            detail="a state cannot both end the journey and be followed by another state",
            triples=(terminal[head], *group),
        )
        for head, group in sorted(successors.items())
    ]


def _required_and_forbidden(
    triples: Sequence[Triple], *, label: Callable[[str], str]
) -> list[Conflict]:
    required: dict[str, list[Triple]] = {}
    forbidden: dict[str, list[Triple]] = {}
    for triple in triples:
        if triple.relation == "RULE_REQUIRES":
            required.setdefault(triple.tail, []).append(triple)
        elif triple.relation == "RULE_FORBIDS":
            forbidden.setdefault(triple.tail, []).append(triple)

    return [
        Conflict(
            kind="deontic",
            heading=f"{label(target)} is both required and forbidden",
            detail=(
                "two rules give opposite obligations for the same target. This is a genuine "
                "contradiction unless the rules carry conditions or exceptions that separate "
                "them, which the corpus does not state."
            ),
            triples=(*required[target], *forbidden[target]),
        )
        for target in sorted(set(required) & set(forbidden))
    ]


def _latest(triples: Sequence[Triple], effective_dates: Mapping[str, str]) -> Triple | None:
    dated: list[tuple[str, Triple]] = []
    for triple in triples:
        dates = {effective_dates.get(span.passage_id, "") for span in triple.spans}
        if not dates or "" in dates or len(dates) > 1:
            return None
        dated.append((dates.pop(), triple))

    dated.sort(key=lambda pair: pair[0])
    if len(dated) < 2 or dated[-1][0] == dated[-2][0]:
        return None
    return dated[-1][1]


def _question(conflict: Conflict) -> Question:
    evidence = tuple(span for triple in conflict.triples for span in triple.spans)
    return Question(
        id=question_id("conflict", conflict.kind, *sorted(_slot(t)[0] for t in conflict.triples)),
        kind=f"conflict/{conflict.kind}",
        heading=conflict.heading,
        detail=conflict.detail,
        blocks=", ".join(sorted({f"{t.head} {t.relation} {t.tail}" for t in conflict.triples})),
        evidence=evidence,
    )


def _slot(triple: Triple) -> tuple[str, str, str, str]:
    """Identity for status updates: the key plus the tail kind, which the key omits."""
    return (triple.head, triple.relation, triple.tail, triple.tail_kind)


def _with_status(triple: Triple, status: str) -> Triple:
    return Triple(
        head=triple.head,
        relation=triple.relation,
        tail=triple.tail,
        tail_kind=triple.tail_kind,
        spans=triple.spans,
        methods=triple.methods,
        materiality=triple.materiality,
        status=status,  # type: ignore[arg-type]
    )
