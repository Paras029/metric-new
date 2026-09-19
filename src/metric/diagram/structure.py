"""The workflow a set of diagrams describes, as a graph rather than as prose about one.

A workflow diagram *is* the operating procedure. A box with branching arrows is a
decision; the label on an arrow leaving it is an outcome; the box that arrow lands in is
a state. Reading one into prose and asking a later pass to rebuild a graph out of that
prose loses the structure twice over, and loses it silently — a dropped box in a
paragraph is invisible, where a dropped box in a node list shows up immediately as an
arrow pointing at nothing.

So the reading passes return structure, and this module holds it, checks it and merges
repairs into it. Nothing here calls a model or opens a file.

**The audit is the load-bearing part.** Every check below is a property the graph needs
in order to be walked at all, which is what makes them worth putting back to the model
with the pictures still in hand: none of them is an opinion about how the workflow should
have been drawn. They are the places the reading is demonstrably incomplete, and naming
them individually turns "read it again, better" into a list of specific holes.

Ids are required and never generated. An invented `D2` would be indistinguishable from
one actually read off a box, and the join pass across several images keys entirely on
them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_ID = re.compile(r"^[A-Z]+-?\d+$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Decision:
    id: str
    name: str
    outcomes: tuple[str, ...]
    at_state: str = ""
    seen_in: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "outcomes": list(self.outcomes),
            "at_state": self.at_state,
            "seen_in": list(self.seen_in),
        }


@dataclass(frozen=True, slots=True)
class State:
    id: str
    name: str
    reached_via: str = ""
    next_decisions: tuple[str, ...] = ()
    next_states: tuple[str, ...] = ()
    terminal: bool = False
    tools: tuple[str, ...] = ()
    seen_in: tuple[str, ...] = ()
    continues: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "reached_via": self.reached_via,
            "next_decisions": list(self.next_decisions),
            "next_states": list(self.next_states),
            "terminal": self.terminal,
            "tools": list(self.tools),
            "seen_in": list(self.seen_in),
            "continues": self.continues,
        }


@dataclass(frozen=True, slots=True)
class Structure:
    states: tuple[State, ...] = ()
    decisions: tuple[Decision, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def empty(self) -> bool:
        return not (self.states or self.decisions)

    @property
    def counts(self) -> dict[str, int]:
        return {"states": len(self.states), "decisions": len(self.decisions)}

    def state(self, identifier: str) -> State | None:
        return next((s for s in self.states if s.id == identifier), None)

    def decision(self, identifier: str) -> Decision | None:
        return next((d for d in self.decisions if d.id == identifier), None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "states": [s.as_dict() for s in self.states],
            "decisions": [d.as_dict() for d in self.decisions],
            "notes": list(self.notes),
        }


def clean(data: Any, *, seen_in: str = "") -> Structure:
    """Keep the well-formed part of what a reading returned, and normalise it.

    Everything except the id gets a defensible default, because a decision whose name
    came back blank is still a decision and still constrains the graph. An entry with no
    usable id is dropped: it cannot be referred to, so nothing else can point at it and
    the audit could not name it.
    """
    if not isinstance(data, dict):
        return Structure()

    states: list[State] = []
    for raw in _objects(data, "states"):
        made = _state(raw, seen_in)
        if made is not None:
            states.append(made)

    decisions: list[Decision] = []
    for raw in _objects(data, "decisions"):
        branch = _decision(raw, seen_in)
        if branch is not None:
            decisions.append(branch)

    return Structure(states=tuple(states), decisions=tuple(decisions))


def audit(structure: Structure) -> tuple[str, ...]:
    """What is structurally wrong, as things a second look at the picture could settle."""
    if structure.empty:
        return ("Nothing was read from the diagrams at all: no states and no decisions.",)

    problems: list[str] = []
    states = {s.id: s for s in structure.states}
    decisions = {d.id: d for d in structure.decisions}
    landings = {
        _route(s.reached_via) for s in structure.states if _route(s.reached_via)
    }

    if not any(s.reached_via.strip().lower() == "start" for s in structure.states):
        problems.append(
            'No state is marked as the start. Exactly one state should have reached_via '
            '"Start" — the position the journey opens in.'
        )

    for decision in structure.decisions:
        if len(decision.outcomes) < 2:
            problems.append(
                f"{decision.id} ({decision.name or 'unnamed'}) has "
                f"{'no' if not decision.outcomes else 'only one'} outcome. A branch with "
                "fewer than two named outcomes is not a branch — look again at the arrows "
                "leaving that box and name each one."
            )
        if decision.at_state and decision.at_state not in states:
            problems.append(
                f"{decision.id} says it sits at {decision.at_state}, and there is no such "
                "state. Either that box was missed or the id is wrong."
            )
        for outcome in decision.outcomes:
            if _key(decision.id, outcome) not in landings:
                problems.append(
                    f'{decision.id} outcome "{outcome}" leads nowhere: no state declares '
                    f"itself reached_via {decision.id}={outcome}. Follow that arrow and say "
                    "where it lands, or say it leaves the page."
                )

    for state in structure.states:
        route = state.reached_via.strip()
        if route and route.lower() != "start":
            identifier, _, outcome = route.partition("=")
            identifier = identifier.strip().upper()
            if identifier not in decisions:
                problems.append(
                    f"{state.id} says it is reached via {route}, and there is no "
                    f"{identifier}. Either that decision was missed, or the state is "
                    "reached some other way."
                )
            elif outcome and outcome.strip().lower() not in {
                o.lower() for o in decisions[identifier].outcomes
            }:
                problems.append(
                    f"{state.id} says it is reached via {route}, but {identifier} declares "
                    f'no outcome called "{outcome.strip()}". One of the two names is wrong.'
                )

        for identifier in state.next_decisions:
            if identifier not in decisions:
                problems.append(
                    f"{state.id} leads to {identifier}, which was not read. That branch is "
                    "either on another image or was missed."
                )
        for identifier in state.next_states:
            if identifier not in states:
                problems.append(
                    f"{state.id} leads straight to {identifier}, which was not read."
                )
        if state.continues and state.continues not in states:
            problems.append(
                f"{state.id} is marked as continuing at {state.continues}, which was not "
                "read. An arrow running off the edge of one image has to land on a box "
                "that another image shows."
            )

    orphans = [
        s
        for s in structure.states
        if not s.reached_via
        and not any(s.id in other.next_states for other in structure.states)
        and not any(s.id == other.continues for other in structure.states)
    ]
    problems.extend(
        f"{s.id} ({s.name or 'unnamed'}) has nothing leading to it and is not the start. "
        "Either an arrow into it was missed, or it is unreachable in the drawing."
        for s in orphans
    )
    return tuple(problems)


def merge(base: Structure, repair: Structure) -> Structure:
    """Fold a repair pass's answer into the structure it was asked to fix.

    A repair replaces an entry it names and adds one it did not have. It never removes:
    a second look that came back quieter than the first is a worse reading, not a
    correction, and silently dropping the first reading's boxes on that basis is how a
    repair pass makes a graph smaller every time it runs.
    """
    states = {s.id: s for s in base.states}
    decisions = {d.id: d for d in base.decisions}

    for state in repair.states:
        existing = states.get(state.id)
        states[state.id] = state if existing is None else _better(existing, state)
    for decision in repair.decisions:
        held = decisions.get(decision.id)
        decisions[decision.id] = decision if held is None else _better_decision(held, decision)

    return Structure(
        states=tuple(sorted(states.values(), key=lambda s: s.id)),
        decisions=tuple(sorted(decisions.values(), key=lambda d: d.id)),
        notes=base.notes + repair.notes,
    )


def _better(existing: State, repair: State) -> State:
    """Take the repair's answer where it gave one, keep the original where it did not."""
    return State(
        id=existing.id,
        name=repair.name or existing.name,
        reached_via=repair.reached_via or existing.reached_via,
        next_decisions=repair.next_decisions or existing.next_decisions,
        next_states=repair.next_states or existing.next_states,
        terminal=repair.terminal or existing.terminal,
        tools=tuple(dict.fromkeys((*existing.tools, *repair.tools))),
        seen_in=tuple(dict.fromkeys((*existing.seen_in, *repair.seen_in))),
        continues=repair.continues or existing.continues,
    )


def _better_decision(existing: Decision, repair: Decision) -> Decision:
    return Decision(
        id=existing.id,
        name=repair.name or existing.name,
        outcomes=repair.outcomes or existing.outcomes,
        at_state=repair.at_state or existing.at_state,
        seen_in=tuple(dict.fromkeys((*existing.seen_in, *repair.seen_in))),
    )


def _state(raw: Any, seen_in: str) -> State | None:
    if not isinstance(raw, dict):
        return None
    identifier = _text(raw, "id").upper()
    if not _ID.match(identifier):
        return None
    return State(
        id=identifier,
        name=_text(raw, "name"),
        reached_via=_text(raw, "reached_via"),
        next_decisions=tuple(x.upper() for x in _strings(raw, "next_decisions")),
        next_states=tuple(x.upper() for x in _strings(raw, "next_states")),
        terminal=bool(raw.get("terminal")),
        tools=tuple(_strings(raw, "tools")),
        seen_in=(seen_in,) if seen_in else (),
        continues=_text(raw, "continues").upper(),
    )


def _decision(raw: Any, seen_in: str) -> Decision | None:
    if not isinstance(raw, dict):
        return None
    identifier = _text(raw, "id").upper()
    if not _ID.match(identifier):
        return None
    return Decision(
        id=identifier,
        name=_text(raw, "name"),
        outcomes=tuple(dict.fromkeys(_strings(raw, "outcomes"))),
        at_state=_text(raw, "at_state").upper(),
        seen_in=(seen_in,) if seen_in else (),
    )


def _objects(data: dict[str, Any], key: str) -> list[Any]:
    found = data.get(key)
    return [x for x in found if isinstance(x, dict)] if isinstance(found, list) else []


def _strings(raw: dict[str, Any], key: str) -> list[str]:
    found = raw.get(key)
    if not isinstance(found, list):
        return []
    return [" ".join(str(x).split()) for x in found if str(x).strip()]


def _text(raw: dict[str, Any], key: str) -> str:
    return " ".join(str(raw.get(key) or "").split())


def _route(reached_via: str) -> str:
    identifier, sep, outcome = reached_via.partition("=")
    return _key(identifier.strip(), outcome.strip()) if sep else ""


def _key(identifier: str, outcome: str) -> str:
    return f"{identifier}={outcome}".lower().replace(" ", "")
