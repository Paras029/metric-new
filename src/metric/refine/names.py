"""Turning extracted names into names.

The extractor names an entity with the words it found it in. For a state or a tool that
is right — the policy says `authenticate_customer` and calls the state "Authentication
attempts". For a rule it is not: policy states rules as sentences, so the graph ended up
with a node called *the bot must not perform any other servicing activity* and another
called *does not perform additional servicing within the POC* and a third called *the bot
does not perform any additional servicing itself*. One rule, stated three times, three
nodes.

That is not a cosmetic problem. Three nodes means three unattached-rule questions for a
human, three `action_forbidden` assertions where one was meant, and a reviewer who cannot
tell which is authoritative. It is also most of the gap the accuracy gate measured: the
facts were read correctly and the subjects were named differently.

Two passes, in that order, because the cheap one is also the more reliable one.

**Deterministic.** Policy documents label their own rules — `**Retry control:** Enforce a
hard maximum…`. Where a surface carries a short label before a colon, that label *is* the
name and no model is needed to see it.

**Model.** What is left needs to know that "must not perform any other servicing activity"
and "does not perform additional servicing within the POC" are the same rule. That is a
judgement about meaning, and it is exactly the thing worth spending a model call on. It
returns a crisp name and, optionally, an existing entity this one restates — chosen from a
closed list, so a merge target cannot be invented.

Renaming changes an entity's id, because identity is a content hash of type and name. So
this runs *before* reconciliation, and a build whose names changed is a different build
with different question ids. That is the correct behaviour and it is worth knowing before
running it over a corpus someone has already reviewed.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from metric.llm.gateway import Gateway
from metric.ontology.canonical import canonical_surface
from metric.ontology.ids import entity_id
from metric.ontology.types import Entity, Triple

# Types whose names should be short. A Turn's tail is the wording itself and a Value is a
# number, so neither is named by this.
NAMED_TYPES = frozenset(
    {"Rule", "State", "Tool", "Outcome", "Decision", "Capability", "Action", "StateVariable"}
)

# How many words a name of each kind may have before it stops being a name. Rules are
# tightest because they are the ones policy states as sentences.
LIMITS: dict[str, int] = {"Rule": 5, "Action": 6}
DEFAULT_LIMIT = 7

_SENTENCE = re.compile(
    r"\b(must|must not|should|shall|may|will|do not|does not|cannot|is|are|treat|ensure)\b",
    re.IGNORECASE,
)
_LABEL = re.compile(r"^\s*[*_#]*\s*([^:]{2,48}?)\s*[*_]*\s*:\s*\S")


@dataclass(frozen=True, slots=True)
class Rename:
    entity: str
    before: str
    after: str
    reason: str
    method: str  # label | model
    merged_into: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "before": self.before,
            "after": self.after,
            "reason": self.reason,
            "method": self.method,
            "merged_into": self.merged_into,
        }


@dataclass(frozen=True, slots=True)
class Refinement:
    entities: tuple[Entity, ...]
    triples: tuple[Triple, ...]
    renames: tuple[Rename, ...]
    merges: tuple[tuple[str, str], ...]
    unresolved: tuple[str, ...]
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "renames": [r.as_dict() for r in self.renames],
            "merges": [list(m) for m in self.merges],
            "unresolved": list(self.unresolved),
            "notes": list(self.notes),
        }


def needs_work(entity: Entity) -> str:
    """Why this name is not a name, or "" when it is one."""
    if entity.type not in NAMED_TYPES:
        return ""
    name = _surface(entity)
    words = name.split()
    limit = LIMITS.get(entity.type, DEFAULT_LIMIT)

    if len(words) > limit:
        return f"{len(words)} words; a {entity.type} should read as a name, not a sentence"
    if _SENTENCE.search(name):
        return "reads as a statement rather than a name"
    if name.rstrip().endswith("."):
        return "ends a sentence"
    return ""


def refine(
    entities: Sequence[Entity],
    triples: Sequence[Triple],
    *,
    gateway: Gateway | None = None,
    quotes: dict[str, tuple[str, ...]] | None = None,
) -> Refinement:
    """Give every entity a name, and merge the ones that turn out to be the same."""
    problems = [(e, why) for e in entities if (why := needs_work(e))]
    if not problems:
        return Refinement(tuple(entities), tuple(triples), (), (), (), ())

    renames: list[Rename] = []
    remaining: list[tuple[Entity, str]] = []
    for entity, why in problems:
        label = _label_of(entity)
        if label:
            renames.append(
                Rename(
                    entity=entity.id,
                    before=_surface(entity),
                    after=label,
                    reason="the source labels it",
                    method="label",
                )
            )
        else:
            remaining.append((entity, why))

    notes: list[str] = []
    if remaining and gateway is not None:
        proposed, failure = _propose(remaining, entities, gateway, quotes or {})
        renames.extend(proposed)
        if failure:
            notes.append(failure)
        remaining = [(e, w) for e, w in remaining if not any(r.entity == e.id for r in proposed)]
    elif remaining:
        notes.append(
            "no model was available, so names that need a judgement about meaning were "
            "left as the extractor wrote them"
        )

    rebuilt, rebuilt_triples, merges = _apply(entities, triples, renames)
    if merges:
        notes.append(
            f"{len(merges)} entities turned out to be restatements of another and were "
            "merged; their spans and surfaces are kept on the survivor"
        )

    return Refinement(
        entities=rebuilt,
        triples=rebuilt_triples,
        renames=tuple(renames),
        merges=merges,
        unresolved=tuple(f"{e.type} {_surface(e)}: {why}" for e, why in remaining),
        notes=tuple(notes),
    )


def _label_of(entity: Entity) -> str:
    """A short label before a colon, which is how policy documents name their own rules."""
    for surface in sorted(entity.surfaces, key=len):
        found = _LABEL.match(surface)
        if not found:
            continue
        label = found.group(1).strip(" *_#")
        if label and len(label.split()) <= LIMITS.get(entity.type, DEFAULT_LIMIT):
            return label
    return ""


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["names"],
    "properties": {
        "names": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["index", "name"],
                "properties": {
                    "index": {"type": "integer"},
                    "name": {
                        "type": "string",
                        "description": "a short noun phrase naming this, at most five words",
                    },
                    "same_as": {
                        "type": "string",
                        "description": (
                            "the name of an existing entity this one restates, copied "
                            "exactly from the list given, or an empty string"
                        ),
                    },
                },
            },
        }
    },
}

_SYSTEM = """You name things that were extracted from a policy document.

Each item below was extracted as an entity but named with the whole sentence it was found
in. Give it a short name: a noun phrase of at most five words, in the document's own
vocabulary, that a reviewer could look up.

Some items are the same thing stated twice. When an item restates one of the existing
entities listed, put that entity's name in `same_as`, copied exactly. Only do this when
they are the same rule or the same thing — not when they are merely related. If in doubt,
leave `same_as` empty; a wrongly merged rule is worse than two rules.

Do not invent. The name must be justified by the text you are given."""


def _propose(
    remaining: Sequence[tuple[Entity, str]],
    everything: Sequence[Entity],
    gateway: Gateway,
    quotes: dict[str, tuple[str, ...]],
) -> tuple[list[Rename], str]:
    existing = sorted(
        {
            _surface(e)
            for e in everything
            if e.type in NAMED_TYPES and not needs_work(e)
        }
    )
    lines = []
    for index, (entity, _) in enumerate(remaining):
        cited = quotes.get(entity.id, ())
        lines.append(
            f"[{index}] type={entity.type}\n"
            f"     extracted as: {_surface(entity)}\n"
            + "".join(f"     source: {q}\n" for q in cited[:3])
        )

    prompt = (
        "ITEMS TO NAME\n" + "\n".join(lines) + "\n\n"
        "EXISTING ENTITIES (valid values for `same_as`)\n"
        + "\n".join(f"- {name}" for name in existing)
    )

    try:
        answer = gateway.json(
            system=_SYSTEM, prompt=prompt, schema=_SCHEMA, label="refine/names"
        )
    except Exception as exc:  # the model is optional; the build continues without it
        return [], (
            f"the naming pass could not reach the model ({type(exc).__name__}), so names "
            "that need a judgement about meaning were left as the extractor wrote them"
        )

    allowed = set(existing)
    found: list[Rename] = []
    for item in answer.get("names") or ():
        index = int(item.get("index", -1))
        if not 0 <= index < len(remaining):
            continue
        entity = remaining[index][0]
        name = str(item.get("name", "")).strip()
        same_as = str(item.get("same_as", "")).strip()
        if same_as and same_as not in allowed:
            same_as = ""
        if not name and not same_as:
            continue
        found.append(
            Rename(
                entity=entity.id,
                before=_surface(entity),
                after=same_as or name,
                reason=(
                    "restates an entity already in the graph"
                    if same_as
                    else "named by the model"
                ),
                method="model",
                merged_into=same_as,
            )
        )
    return found, ""


def _apply(
    entities: Sequence[Entity], triples: Sequence[Triple], renames: Sequence[Rename]
) -> tuple[tuple[Entity, ...], tuple[Triple, ...], tuple[tuple[str, str], ...]]:
    """Rewrite ids, then fold any entities that now share one.

    Identity is a content hash of type and name, so a rename is an id change and every
    triple that referenced the old id has to move with it. Two entities that land on the
    same id were the same thing named twice, which is the point.
    """
    by_id = {e.id: e for e in entities}
    mapping: dict[str, str] = {}
    renamed: dict[str, Entity] = {}

    for rename in renames:
        entity = by_id.get(rename.entity)
        if entity is None:
            continue
        canonical = canonical_surface(entity.type, rename.after)
        new_id = entity_id(entity.type, canonical)
        mapping[entity.id] = new_id
        renamed[entity.id] = replace(
            entity, id=new_id, canonical=canonical, surfaces=entity.surfaces | {rename.after}
        )

    merged: dict[str, Entity] = {}
    collisions: list[tuple[str, str]] = []
    for entity in entities:
        moved = renamed.get(entity.id, entity)
        existing = merged.get(moved.id)
        if existing is None:
            merged[moved.id] = moved
            continue
        collisions.append((_surface(moved), _surface(existing)))
        merged[moved.id] = replace(existing, surfaces=existing.surfaces | moved.surfaces)

    rebuilt = tuple(
        replace(
            t,
            head=mapping.get(t.head, t.head),
            tail=mapping.get(t.tail, t.tail) if t.tail_kind == "entity" else t.tail,
        )
        for t in triples
    )
    return tuple(sorted(merged.values(), key=lambda e: e.id)), rebuilt, tuple(collisions)


def _surface(entity: Entity) -> str:
    """The name a person would recognise: the shortest surface the corpus used."""
    return min(entity.surfaces, key=len) if entity.surfaces else entity.canonical
