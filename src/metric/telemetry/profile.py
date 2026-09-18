"""Telemetry profiles: what the ontology is called on the wire.

No policy names a span attribute, so these bindings can never come from ingestion.
They are declared by a person who has looked at both the ontology and the traces, and
that is the whole point: a second agent emitting different names needs a new profile,
not new code. This is the seam the design rests on for transferability.

The production trace makes the case. It carries no `step_id`, no turn state, no
counter — but `set_metadata` writes `("checkpoint", "check14Key")`, tool arguments
carry `no_user_pref_counter`, and tool outputs carry `{"match": "NO_USER_RESPONSE"}`.
Every one of those is a name that maps to something the ontology already has. Binding
is a mapping table, not an embedding problem, and this file is the table.

Profile triples enter the graph as declarations, with `telemetry` as their method and
the profile itself as their evidence. They are not extractions and do not pretend to
be: nothing in the corpus supports them, and the provenance says so.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from metric.graph.model import Graph, build
from metric.ontology.canonical import canonical_surface
from metric.ontology.ids import entity_id
from metric.ontology.types import Span, Triple

# section in the profile -> (entity type, the relation that records the binding)
SECTIONS: dict[str, tuple[str, str]] = {
    "capabilities": ("Capability", "EMITTED_AS_WORKFLOW"),
    "tools": ("Tool", "EMITTED_AS_TOOL"),
    "outcomes": ("Outcome", "EMITTED_AS_RESULT"),
    "states": ("State", "EMITTED_AS_CHECKPOINT"),
    "variables": ("StateVariable", "EMITTED_AS_FIELD"),
}


class ProfileError(Exception):
    """Raised when a profile is malformed or names something the ontology does not have."""


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    source: str
    bindings: dict[str, dict[str, str]] = field(default_factory=dict)
    checkpoint_variable: str = ""

    def count(self) -> int:
        return sum(len(section) for section in self.bindings.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "checkpoint_variable": self.checkpoint_variable,
            "bindings": self.bindings,
        }


def load_profile(path: Path) -> Profile:
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    if not isinstance(document, dict):
        raise ProfileError(f"{path} does not contain a YAML mapping")

    bindings: dict[str, dict[str, str]] = {}
    for section in SECTIONS:
        raw = document.get(section) or {}
        if not isinstance(raw, Mapping):
            raise ProfileError(f"{path}: {section} must be a mapping of ontology name to span name")
        bindings[section] = {str(key): str(value) for key, value in raw.items()}

    unknown = set(document) - set(SECTIONS) - {
        "version", "name", "use_case", "notes", "checkpoint_variable",
    }
    if unknown:
        raise ProfileError(
            f"{path}: unknown sections {sorted(unknown)}; expected {sorted(SECTIONS)}"
        )

    return Profile(
        name=str(document.get("name") or path.stem),
        source=str(path),
        bindings=bindings,
        checkpoint_variable=str(document.get("checkpoint_variable") or ""),
    )


def apply_profile(graph: Graph, profile: Profile) -> tuple[Graph, list[str]]:
    """Add the profile's bindings to the graph, reporting names the ontology lacks.

    A binding for an entity that is not in the graph is a mistake worth seeing — it
    usually means the profile was written against a different build of the ontology —
    so it is reported rather than silently creating a node nothing else refers to.
    """
    known = {entity.id for entity in graph.entities}
    triples = list(graph.triples)
    problems: list[str] = []

    for section, (entity_type, relation) in SECTIONS.items():
        for ontology_name, span_name in sorted(profile.bindings.get(section, {}).items()):
            head = entity_id(entity_type, canonical_surface(entity_type, ontology_name))
            if head not in known:
                problems.append(
                    f"{section}: the ontology has no {entity_type} called {ontology_name!r}"
                )
                continue
            triples.append(
                Triple(
                    head=head,
                    relation=relation,
                    tail=span_name,
                    tail_kind="literal",
                    spans=(_evidence(profile, section, ontology_name, span_name),),
                    methods=frozenset({"telemetry"}),
                    materiality="high",
                    status="admitted",
                )
            )

    return build(graph.entities, triples), problems


def _evidence(profile: Profile, section: str, ontology_name: str, span_name: str) -> Span:
    quote = f"{section}: {ontology_name} -> {span_name}"
    return Span(passage_id=f"profile:{profile.name}", start=0, end=len(quote), quote=quote)
