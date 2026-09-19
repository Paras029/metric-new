"""Rules that assert nothing.

Nine of the fourteen rules in the working build carried exactly two things: their own
text, and a severity. Nothing was governed by them and they required, forbade and bounded
nothing. A rule like that cannot compile to an assertion, cannot fail an agent, and cannot
be acted on — and each one raised a question whose only sensible answer was "yes, that is
useless".

The extractor is not hallucinating when it produces them. Policy documents restate their
own rules — a summary in §1, an evaluation checklist in §7 — and each restatement is a
real sentence that really does read like a rule. What the extractor missed is the *clause*:
it found "the bot must not perform any other servicing" and recorded that the sentence
exists, without recording what it forbids.

So an inert rule is a **recall defect**, not noise, and the treatment follows from that:

- It is taken out of the graph, because a node that can produce no assertion is a node a
  reviewer has to read and dismiss, and because the summary it came from is almost always
  a restatement of a rule the graph already holds properly.
- It is reported as **one** question naming all of them, not one question each. Nine
  identical questions is not nine decisions.
- Its text is quoted in that question, so the gap is visible rather than erased. If a rule
  was genuinely missed rather than restated, that is where it will be noticed.

What counts as inert is read from the schema, not hardcoded: a rule is inert when none of
its outgoing relations declares a check and nothing is governed by it. A use case that adds
its own checkable relation gets this for free.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from metric.ontology.schema import Schema
from metric.ontology.types import Entity, Triple

# Relations by which something is put *under* a rule. A rule that governs something is
# doing work even if its own clause was missed.
ATTACHING = ("GOVERNED_BY",)


@dataclass(frozen=True, slots=True)
class Inert:
    entity: str
    name: str
    entity_type: str
    states: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "name": self.name,
            "type": self.entity_type,
            "states": self.states,
        }


@dataclass(frozen=True, slots=True)
class Pruned:
    entities: tuple[Entity, ...]
    triples: tuple[Triple, ...]
    removed: tuple[Inert, ...]

    @property
    def note(self) -> str:
        if not self.removed:
            return ""
        return (
            f"{len(self.removed)} rules were extracted but state no requirement, "
            "prohibition or limit and govern nothing, so they could not have been checked "
            "against anything. They are listed rather than dropped silently: each is "
            "either a restatement of a rule the graph already holds, or a rule whose "
            "clause was missed"
        )

    def as_dict(self) -> dict[str, Any]:
        return {"removed": [i.as_dict() for i in self.removed], "note": self.note}


def prune(
    entities: Sequence[Entity], triples: Sequence[Triple], schema: Schema
) -> Pruned:
    """Take out the rules that could never have been checked against anything."""
    checkable = {
        name for name, spec in schema.relations.items() if spec.checks is not None
    }
    attached = {t.tail for t in triples if t.relation in ATTACHING}

    working: set[str] = set()
    states: dict[str, str] = {}
    for triple in triples:
        if triple.relation in checkable:
            working.add(triple.head)
        if triple.relation == "RULE_STATES":
            states.setdefault(triple.head, triple.tail)

    inert = tuple(
        Inert(
            entity=entity.id,
            name=min(entity.surfaces, key=len) if entity.surfaces else entity.canonical,
            entity_type=entity.type,
            states=states.get(entity.id, ""),
        )
        for entity in entities
        if entity.type == "Rule" and entity.id not in working and entity.id not in attached
    )
    if not inert:
        return Pruned(tuple(entities), tuple(triples), ())

    gone = {i.entity for i in inert}
    return Pruned(
        entities=tuple(e for e in entities if e.id not in gone),
        triples=tuple(
            t
            for t in triples
            if t.head not in gone and not (t.tail_kind == "entity" and t.tail in gone)
        ),
        removed=inert,
    )
