"""Where was the conversation at each turn?

This is the hinge of the whole reverse direction. Everything a knowledge graph knows
is anchored to a state — which tools belong there, which outcomes are legal, where it
may go next, which rules are in force — so until a turn is placed in the graph, none of
that can be brought to bear on it. Bind the turn and the ground truth for it falls out.

Four mechanisms, tried in order, and the order is the honest one:

1. **checkpoint** — the agent said so itself, through a `set_metadata` write that binds
   to a State. Certain, and the only mechanism that is.
2. **inferred** — the agent did not say, but what it *did* pins it. This is the "two of
   three" reading: a tool belongs to particular states, an outcome is produced by a
   particular decision, and a decision is offered from a particular state. Intersect
   those with what is reachable from the previous turn and often exactly one state
   survives.
3. **carried** — nothing this turn moved or revealed anything, so the conversation is
   where it was. An assumption, and labelled as one.
4. **none** — say so.

Confidence is not a probability and is not dressed up as one. It orders bindings so a
reviewer sees the shaky ones first, and `certain` is the only thing that gates whether
a turn's ground truth is allowed to fail an agent. The strategy notes are explicit
about this: a low-confidence binding must surface as uncertainty, not quietly become a
hard verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from metric.graph.journey import Journey
from metric.graph.model import Graph
from metric.trace.binding import BoundTrace

Method = Literal["checkpoint", "inferred", "ambiguous", "carried", "none"]

CONFIDENCE: dict[Method, float] = {
    "checkpoint": 1.0,
    "inferred": 0.8,
    "carried": 0.6,
    "ambiguous": 0.4,
    "none": 0.0,
}


@dataclass(frozen=True, slots=True)
class StateBinding:
    """Where a turn was. Possibly more than one place.

    A turn is not an atom: the working trace writes `authenticating` and then `retry`
    inside one turn, and collapsing that to a single state loses the hop between them
    and makes the tools called there look like they belong somewhere else. `states`
    holds the visits in order; `state` is where the turn began and `exit_state` where
    it ended.
    """

    turn: int
    states: tuple[str, ...]
    method: Method
    alternatives: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    reason: str = ""

    @property
    def state(self) -> str | None:
        return self.states[0] if self.states else None

    @property
    def exit_state(self) -> str | None:
        return self.states[-1] if self.states else None

    @property
    def confidence(self) -> float:
        base = CONFIDENCE[self.method]
        if self.method == "ambiguous" and self.alternatives:
            return round(base / len(self.alternatives), 3)
        return base

    @property
    def certain(self) -> bool:
        """Only a checkpoint is certain. Everything else is a reading, however good."""
        return self.method == "checkpoint"

    def as_dict(self) -> dict[str, object]:
        return {
            "turn": self.turn,
            "states": list(self.states),
            "state": self.state,
            "exit_state": self.exit_state,
            "method": self.method,
            "confidence": self.confidence,
            "alternatives": list(self.alternatives),
            "evidence": list(self.evidence),
            "reason": self.reason,
        }


def bind_states(bound: BoundTrace, graph: Graph) -> tuple[StateBinding, ...]:
    journey = Journey(graph)
    reverse = _Reverse(graph, journey)

    bindings: list[StateBinding] = []
    previous: str | None = None

    for turn in sorted({b.observation.turn for b in bound.bindings}):
        binding = _bind_turn(bound, journey, reverse, turn, previous)
        bindings.append(binding)
        if binding.exit_state is not None:
            previous = binding.exit_state

    return tuple(bindings)


def _bind_turn(
    bound: BoundTrace, journey: Journey, reverse: _Reverse, turn: int, previous: str | None
) -> StateBinding:
    declared = [
        b
        for b in bound.bindings
        if b.observation.turn == turn and b.entity_type == "State" and b.entity
    ]
    if declared:
        visits: list[str] = []
        for binding in declared:
            if binding.entity and (not visits or visits[-1] != binding.entity):
                visits.append(binding.entity)
        wrote = ", ".join(repr(b.token) for b in declared)
        return StateBinding(
            turn=turn,
            states=tuple(visits),
            method="checkpoint",
            evidence=tuple(b.observation.ref for b in declared),
            reason=f"the agent wrote {wrote} to its own checkpoint",
        )

    tools = [b for b in bound.bindings if b.observation.turn == turn and b.entity_type == "Tool"]
    outcomes = [
        b for b in bound.bindings if b.observation.turn == turn and b.entity_type == "Outcome"
    ]
    evidence = tuple(b.observation.ref for b in (*tools, *outcomes) if b.entity)

    candidates = reverse.states_for(
        tools=[b.entity for b in tools if b.entity],
        outcomes=[b.entity for b in outcomes if b.entity],
    )
    if previous is not None and candidates:
        reachable = reverse.reachable_from(previous)
        narrowed = candidates & reachable
        if narrowed:
            candidates = narrowed

    if len(candidates) == 1:
        state = next(iter(candidates))
        return StateBinding(
            turn=turn,
            states=(state,),
            method="inferred",
            evidence=evidence,
            reason="only one state uses what this turn did",
        )

    if len(candidates) > 1:
        ordered = tuple(sorted(candidates))
        return StateBinding(
            turn=turn,
            states=(ordered[0],),
            method="ambiguous",
            alternatives=ordered,
            evidence=evidence,
            reason=f"{len(ordered)} states could account for this turn",
        )

    if previous is not None:
        return StateBinding(
            turn=turn,
            states=(previous,),
            method="carried",
            reason="nothing in this turn moved or revealed the state, so it is assumed unchanged",
        )

    return StateBinding(
        turn=turn,
        states=(),
        method="none",
        reason="no checkpoint, and nothing observed that any state accounts for",
    )


class _Reverse:
    """The graph read backwards: from what was seen to where it could have been seen.

    Forward, a state says which tools it uses and which outcomes follow. Inverted,
    a tool says which states could have called it and an outcome says which decision
    produced it — and a decision is offered from a state. That inversion is the whole
    trick, and it is a dictionary, not a model.
    """

    def __init__(self, graph: Graph, journey: Journey) -> None:
        self.journey = journey

        self.by_tool: dict[str, set[str]] = {}
        states = set(graph.ids_of_type("State"))
        for triple in graph.by_relation("USES_TOOL"):
            if triple.head in states:
                self.by_tool.setdefault(triple.tail, set()).add(triple.head)

        offered: dict[str, set[str]] = {}
        for triple in graph.by_relation("OFFERS_DECISION"):
            offered.setdefault(triple.tail, set()).add(triple.head)

        self.by_outcome: dict[str, set[str]] = {}
        for triple in graph.by_relation("HAS_OUTCOME"):
            for state in offered.get(triple.head, ()):
                self.by_outcome.setdefault(triple.tail, set()).add(state)

    def states_for(self, *, tools: list[str], outcomes: list[str]) -> set[str]:
        """States that account for everything observed, or failing that, anything.

        An intersection is the right answer when the turn's observations all belong to
        one state. When they do not — a turn that spans a transition — the union is
        what is left, and the ambiguity is reported rather than resolved by preference.
        """
        seen = [self.by_tool.get(t, set()) for t in tools]
        seen += [self.by_outcome.get(o, set()) for o in outcomes]
        seen = [s for s in seen if s]
        if not seen:
            return set()

        together = set.intersection(*seen)
        return together or set.union(*seen)

    def reachable_from(self, state: str) -> set[str]:
        """Where the conversation could be, having been at `state`: here, or one step on."""
        return {state} | {target for _, _, target in self.journey.successors(state)}
