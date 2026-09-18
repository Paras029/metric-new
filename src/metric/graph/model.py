"""The graph, and the few lookups everything downstream needs.

Held in memory as sorted tuples rather than an index, because a build's graph is
thousands of triples, not millions, and a canonical sort is what makes two builds
byte-comparable. When that stops being true the store changes; nothing else has to.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from metric.ontology.types import Entity, Triple


@dataclass(frozen=True, slots=True)
class Graph:
    entities: tuple[Entity, ...]
    triples: tuple[Triple, ...]

    @property
    def admitted(self) -> tuple[Triple, ...]:
        """Facts the build stands behind without qualification."""
        return tuple(t for t in self.triples if t.status == "admitted")

    @property
    def live(self) -> tuple[Triple, ...]:
        """Everything the build is proposing, including what is awaiting review.

        The traversals below read this rather than `admitted`, because a fact held for
        review is still a fact the build found, and integrity questions about it are
        exactly what a reviewer needs alongside it. Only `conflicted` and `superseded`
        triples drop out.
        """
        return tuple(t for t in self.triples if t.status in {"admitted", "review"})

    def entity(self, entity_id: str) -> Entity | None:
        return next((e for e in self.entities if e.id == entity_id), None)

    def label(self, entity_id: str) -> str:
        """A human-readable name for an id, falling back to the id itself."""
        found = self.entity(entity_id)
        return sorted(found.surfaces)[0] if found and found.surfaces else entity_id

    def by_relation(self, relation: str) -> tuple[Triple, ...]:
        return tuple(t for t in self.live if t.relation == relation)

    def out(self, head: str, relation: str | None = None) -> tuple[Triple, ...]:
        return tuple(
            t
            for t in self.live
            if t.head == head and (relation is None or t.relation == relation)
        )

    def ids_of_type(self, entity_type: str) -> tuple[str, ...]:
        return tuple(e.id for e in self.entities if e.type == entity_type)

    def as_dict(self) -> dict[str, Any]:
        return {
            "entities": [e.as_dict() for e in self.entities],
            "triples": [t.as_dict() for t in self.triples],
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.as_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def read(cls, path: Path) -> Graph:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        entities = tuple(
            Entity(
                id=str(e["id"]),
                type=str(e["type"]),
                canonical=str(e["canonical"]),
                surfaces=frozenset(e["surfaces"]),
            )
            for e in data["entities"]
        )
        return cls(entities=entities, triples=tuple(Triple.from_dict(t) for t in data["triples"]))


def build(entities: Iterable[Entity], triples: Iterable[Triple]) -> Graph:
    """Assemble a graph in canonical order."""
    return Graph(
        entities=tuple(sorted(entities, key=lambda e: (e.type, e.canonical))),
        triples=tuple(sorted(triples, key=lambda t: (t.head, t.relation, t.tail))),
    )
