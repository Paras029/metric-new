"""Turning observations into two files a person then owns.

A telemetry profile and an observation file. Both are YAML, both are drafts, and the
point of writing them out rather than holding them in memory is that a person edits
them: renames a checkpoint to something a reader understands, drops the tool that
turned out to be a health check, decides which of three candidate variables is
actually the journey.

The observation file becomes graph facts with `telemetry` as their method and a trace
span as their evidence. It is deliberately not the same shape as a policy extraction —
nothing here is grounded in a document, and a format that made the two look alike would
invite exactly the confusion that matters most to avoid.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from metric.discover.observe import Observed
from metric.graph.model import Graph, build
from metric.ontology.canonical import canonical_surface
from metric.ontology.ids import entity_id
from metric.ontology.types import Entity, Span, Triple


class ObservationError(Exception):
    """Raised when an observation file cannot be read."""


def profile_yaml(found: Observed, *, name: str, use_case: str) -> str:
    """A profile skeleton: every observed name mapped to itself, ready to be renamed."""
    checkpoint = found.checkpoint_variable()
    states = {value: value for value in found.states(checkpoint)} if checkpoint else {}

    document: dict[str, Any] = {
        "version": 1,
        "name": name,
        "use_case": use_case,
        "capabilities": {k: k for k in sorted(found.capabilities)},
        "tools": {k: k for k in sorted(found.tools)},
        "outcomes": {k: k for k in sorted(found.outcomes)},
        "states": states,
        "variables": {k: k for k in sorted(found.variables) if k != checkpoint},
    }
    if checkpoint:
        document["checkpoint_variable"] = checkpoint

    header = _header(found, checkpoint)
    return header + _dump(document)


def observation_yaml(found: Observed, *, name: str, use_case: str) -> str:
    checkpoint = found.checkpoint_variable()
    document: dict[str, Any] = {
        "version": 1,
        "name": name,
        "use_case": use_case,
        "checkpoint_variable": checkpoint,
        "traces": list(found.traces),
        "capabilities": sorted(found.capabilities),
        "tools": sorted(found.tools),
        "outcomes": {k: sorted(v) for k, v in sorted(found.outcomes.items())},
        "states": found.states(checkpoint),
        "transitions": [
            [source, target]
            for source, targets in sorted(found.transitions.items())
            for target, _ in targets.most_common()
            if source in found.states(checkpoint) and target in found.states(checkpoint)
        ],
        "variables": sorted(k for k in found.variables if k != checkpoint),
        "state_tools": {
            state: sorted(tools)
            for state, tools in sorted(found.state_tools.items())
            if state in found.states(checkpoint)
        },
        "evidence": {k: v for k, v in sorted(found.first_seen.items()) if k},
    }
    return _OBSERVED_HEADER + _dump(document)


def _dump(document: dict[str, Any]) -> str:
    text: str = yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=96)
    return text


def load_observations(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    if not isinstance(document, dict):
        raise ObservationError(f"{path} does not contain a YAML mapping")
    if not document.get("use_case"):
        raise ObservationError(f"{path}: no use_case, so there is nothing to attach these to")

    if "state_tools" in document and not isinstance(document["state_tools"], Mapping):
        raise ObservationError(f"{path}: state_tools must be a mapping")
    for key in ("capabilities", "tools", "states", "variables", "traces"):
        if key in document and not isinstance(document[key], list):
            raise ObservationError(f"{path}: {key} must be a list")
    for key in ("outcomes", "evidence"):
        if key in document and not isinstance(document[key], Mapping):
            raise ObservationError(f"{path}: {key} must be a mapping")
    for pair in document.get("transitions") or ():
        if not isinstance(pair, list) or len(pair) != 2:
            raise ObservationError(f"{path}: every transition must be a [from, to] pair")

    return document


def apply_observations(graph: Graph, document: Mapping[str, Any]) -> Graph:
    """Merge observed structure into a graph as telemetry-sourced facts."""
    use_case = str(document["use_case"])
    evidence: Mapping[str, str] = document.get("evidence") or {}
    conversation = ", ".join(str(t) for t in document.get("traces") or ()) or "trace"

    entities: dict[str, Entity] = {e.id: e for e in graph.entities}
    triples = list(graph.triples)

    def node(entity_type: str, surface: str) -> str:
        identifier = entity_id(entity_type, canonical_surface(entity_type, surface))
        existing = entities.get(identifier)
        entities[identifier] = Entity(
            id=identifier,
            type=entity_type,
            canonical=canonical_surface(entity_type, surface),
            surfaces=(existing.surfaces if existing else frozenset()) | {surface},
        )
        return identifier

    def fact(head: str, relation: str, tail: str, *, surface: str, literal: bool = False) -> None:
        quote = f"observed in {conversation} at {evidence.get(surface, 'an unrecorded span')}"
        triples.append(
            Triple(
                head=head,
                relation=relation,
                tail=tail,
                tail_kind="literal" if literal else "entity",
                spans=(Span(passage_id=f"observed:{conversation}", start=0, end=len(quote),
                            quote=quote),),
                methods=frozenset({"telemetry"}),
                materiality="normal",
                status="admitted",
            )
        )

    journey = node("UseCase", use_case)
    capabilities = [node("Capability", c) for c in document.get("capabilities") or ()]
    for capability, surface in zip(capabilities, document.get("capabilities") or (), strict=True):
        fact(journey, "HAS_CAPABILITY", capability, surface=surface)

    anchor = capabilities[0] if capabilities else journey
    anchor_relation = "HAS_STATE" if capabilities else "STARTS_AT"

    states = {s: node("State", s) for s in document.get("states") or ()}
    for surface, state in states.items():
        if capabilities:
            fact(anchor, anchor_relation, state, surface=surface)

    for source, target in document.get("transitions") or ():
        if source in states and target in states:
            fact(states[source], "HAS_NEXT_STEP", states[target], surface=source)

    entered = {t for _, t in document.get("transitions") or ()}
    for surface, state in states.items():
        if surface not in entered:
            fact(journey, "STARTS_AT", state, surface=surface)

    tools = {t: node("Tool", t) for t in document.get("tools") or ()}
    attributed = document.get("state_tools") or {}
    for state_surface, used in attributed.items():
        if state_surface not in states:
            continue
        for surface in used:
            if surface in tools:
                fact(states[state_surface], "USES_TOOL", tools[surface], surface=surface)

    placed = {t for used in attributed.values() for t in used}
    for surface, tool in tools.items():
        if capabilities and surface not in placed:
            fact(anchor, "USES_TOOL", tool, surface=surface)

    for token, sources in (document.get("outcomes") or {}).items():
        outcome = node("Outcome", str(token))
        for source in sources:
            if source in tools:
                fact(tools[source], "RETURNS", outcome, surface=str(token))

    for surface in document.get("variables") or ():
        variable = node("StateVariable", str(surface))
        fact(anchor if capabilities else journey, "HAS_STATE_VARIABLE", variable, surface=surface)

    return build(entities.values(), triples)


def _header(found: Observed, checkpoint: str) -> str:
    alternatives = [c for c in found.checkpoint_candidates if c != checkpoint]
    lines = [
        "# Drafted by `metric discover` from "
        + (", ".join(found.traces) or "no traces")
        + ".",
        "#",
        "# Every name maps to itself to start with. Rename the left-hand side to whatever the",
        "# ontology calls the thing; the right-hand side is what the agent emits and must stay",
        "# exactly as observed.",
    ]
    if alternatives:
        lines += [
            "#",
            "# Other variables also looked like checkpoints: " + ", ".join(alternatives) + ".",
            "# Only one can be the journey. Change `checkpoint_variable` if this guess is wrong.",
        ]
    return "\n".join(lines) + "\n"


_OBSERVED_HEADER = """\
# Drafted by `metric discover`. This is what an agent was seen to do, not what policy
# says it should do -- so nothing here can fail that agent. It exists to bind traces,
# to show coverage, and to give whoever writes the real ontology a starting shape.
"""
