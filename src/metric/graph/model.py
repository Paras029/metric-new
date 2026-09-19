"""The graph, and the few lookups everything downstream needs.

Canonically sorted tuples are the storage, because that sort is what makes two builds
byte-comparable. The lookups are indexed on top of them: a linear scan per `label()`
is quadratic over a page render, and measurably so — at three thousand entities the
scans alone cost more than the entire build.

The indexes are derived, never part of identity. `as_dict` and equality see the tuples
only, so an index can never make two graphs that should be identical differ.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from metric.ontology.types import Entity, Triple

_LIVE = frozenset({"admitted", "review"})


@dataclass(frozen=True, slots=True)
class Graph:
    entities: tuple[Entity, ...]
    triples: tuple[Triple, ...]

    _index: _Index = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_index", _Index(self.entities, self.triples))

    @property
    def admitted(self) -> tuple[Triple, ...]:
        """Facts the build stands behind without qualification."""
        return tuple(t for t in self.triples if t.status == "admitted")

    @property
    def live(self) -> tuple[Triple, ...]:
        """Everything the build is proposing, including what is awaiting review.

        The traversals below read this rather than `admitted`, because a fact held for
        review is still a fact the build found, and integrity questions about it are
        exactly what a reviewer needs alongside it. Only `conflicted`, `superseded` and
        `rejected` triples drop out.
        """
        return self._index.live

    def entity(self, entity_id: str) -> Entity | None:
        return self._index.by_id.get(entity_id)

    def label(self, entity_id: str) -> str:
        """A human-readable name for an id, falling back to the id itself."""
        return self._index.labels.get(entity_id, entity_id)

    def by_relation(self, relation: str) -> tuple[Triple, ...]:
        return self._index.by_relation.get(relation, ())

    def out(self, head: str, relation: str | None = None) -> tuple[Triple, ...]:
        leaving = self._index.out.get(head, ())
        if relation is None:
            return leaving
        return tuple(t for t in leaving if t.relation == relation)

    def ids_of_type(self, entity_type: str) -> tuple[str, ...]:
        return self._index.by_type.get(entity_type, ())

    def touching(self, entity_id: str) -> tuple[Triple, ...]:
        """Every live triple this entity appears in, on either side."""
        return self._index.touching.get(entity_id, ())

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


@dataclass(frozen=True, slots=True)
class _Index:
    """Derived lookups. Built once per graph, never part of what a graph *is*."""

    by_id: dict[str, Entity]
    labels: dict[str, str]
    by_type: dict[str, tuple[str, ...]]
    live: tuple[Triple, ...]
    by_relation: dict[str, tuple[Triple, ...]]
    out: dict[str, tuple[Triple, ...]]
    touching: dict[str, tuple[Triple, ...]]

    def __init__(self, entities: tuple[Entity, ...], triples: tuple[Triple, ...]) -> None:
        by_id: dict[str, Entity] = {}
        labels: dict[str, str] = {}
        by_type: dict[str, list[str]] = {}
        for entity in entities:
            by_id[entity.id] = entity
            labels[entity.id] = sorted(entity.surfaces)[0] if entity.surfaces else entity.id
            by_type.setdefault(entity.type, []).append(entity.id)

        live = tuple(t for t in triples if t.status in _LIVE)
        by_relation: dict[str, list[Triple]] = {}
        out: dict[str, list[Triple]] = {}
        touching: dict[str, list[Triple]] = {}
        for triple in live:
            by_relation.setdefault(triple.relation, []).append(triple)
            out.setdefault(triple.head, []).append(triple)
            touching.setdefault(triple.head, []).append(triple)
            if triple.tail_kind == "entity":
                touching.setdefault(triple.tail, []).append(triple)

        for name, value in (
            ("by_id", by_id),
            ("labels", labels),
            ("by_type", {k: tuple(v) for k, v in by_type.items()}),
            ("live", live),
            ("by_relation", {k: tuple(v) for k, v in by_relation.items()}),
            ("out", {k: tuple(v) for k, v in out.items()}),
            ("touching", {k: tuple(v) for k, v in touching.items()}),
        ):
            object.__setattr__(self, name, value)


def build(entities: Iterable[Entity], triples: Iterable[Triple]) -> Graph:
    """Assemble a graph in canonical order."""
    return Graph(
        entities=tuple(sorted(entities, key=lambda e: (e.type, e.canonical))),
        triples=tuple(sorted(triples, key=lambda t: (t.head, t.relation, t.tail))),
    )
