"""Pass A: harvest the entity vocabulary, then freeze it.

The point of a separate pass is order-independence. Accumulating a glossary while
extracting makes batch *N* depend on batches 1…*N*−1: reordering the corpus would
change the graph, and a bad entity introduced early would propagate forward through
every later batch. Reading every batch for entities first, merging, and only then
extracting removes both properties for roughly a third more calls.

Merging is by canonical name and the result is sorted, so the frozen glossary is a
function of the passage set rather than of the order it was processed in.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from metric.extract.batching import Batch
from metric.llm import prompts
from metric.llm.gateway import Gateway
from metric.ontology.ids import canonical_name
from metric.ontology.schema import Schema


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    canonical: str
    surfaces: tuple[str, ...]
    types: tuple[str, ...]

    @property
    def contested(self) -> bool:
        return len(self.types) > 1

    def render(self) -> str:
        primary, *aliases = self.surfaces
        line = f"- {primary}"
        if aliases:
            line += f" (also written: {', '.join(aliases)})"
        return f"{line} — {' or '.join(self.types)}"


@dataclass(frozen=True, slots=True)
class Glossary:
    entries: tuple[GlossaryEntry, ...]

    @property
    def contested(self) -> tuple[GlossaryEntry, ...]:
        """Surface forms two batches typed differently.

        Kept rather than resolved: the disagreement is evidence about the document,
        and picking a winner here would bury it.
        """
        return tuple(entry for entry in self.entries if entry.contested)

    def render(self) -> str:
        return "\n".join(entry.render() for entry in self.entries)


def build_glossary(
    batches: Sequence[Batch],
    *,
    gateway: Gateway,
    schema: Schema,
) -> Glossary:
    system = prompts.glossary_system(schema)
    response_schema = prompts.glossary_schema(schema)
    known = schema.entity_types

    surfaces: dict[str, set[str]] = {}
    types: dict[str, set[str]] = {}

    for batch in batches:
        response = gateway.json(
            system=system,
            prompt=prompts.glossary_prompt(batch),
            schema=response_schema,
            label=f"glossary[{batch.id}]",
        )
        for item in response.get("entities", ()):
            surface = str(item.get("surface", "")).strip()
            entity_type = str(item.get("type", ""))
            if not surface or entity_type not in known:
                continue
            key = canonical_name(surface)
            if not key:
                continue
            surfaces.setdefault(key, set()).add(surface)
            types.setdefault(key, set()).add(entity_type)

    entries = tuple(
        GlossaryEntry(
            canonical=key,
            surfaces=tuple(sorted(surfaces[key])),
            types=tuple(sorted(types[key])),
        )
        for key in sorted(surfaces)
    )
    return Glossary(entries=entries)
