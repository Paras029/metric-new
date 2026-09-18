"""What a trace is reduced to before anything grades it.

An `Observation` is one thing the agent demonstrably did, taken from a span and
nothing else. Deriving observations first, and only then binding them to ontology
entities, is what keeps "the agent called a tool we do not know about" distinct from
"the agent did not call the tool". Collapsing those two is how an evaluator ends up
confidently grading its own blind spot.

Nothing here interprets. `silence` is an observation, not an error: a turn that
produced no tool call is a fact about the run and has to be assertable against.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

ObservationKind = Literal[
    "utterance",  # what the customer was heard to say
    "assistant",  # what the agent said back
    "capability",  # a workflow span: which journey the agent selected
    "tool_call",  # a tool invocation, with its arguments
    "outcome",  # a symbolic result the tool returned
    "state_write",  # an explicit (variable, value) assignment
    "silence",  # the turn produced no tool call at all
]


@dataclass(frozen=True, slots=True)
class Observation:
    turn: int
    step: int
    kind: ObservationKind
    name: str
    value: str
    ref: str
    arguments: tuple[tuple[str, str], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "step": self.step,
            "kind": self.kind,
            "name": self.name,
            "value": self.value,
            "ref": self.ref,
            "arguments": [list(pair) for pair in self.arguments],
        }


@dataclass(frozen=True, slots=True)
class Turn:
    index: int
    name: str
    observations: tuple[Observation, ...]

    def of_kind(self, *kinds: ObservationKind) -> tuple[Observation, ...]:
        return tuple(o for o in self.observations if o.kind in kinds)

    @property
    def silent(self) -> bool:
        return any(o.kind == "silence" for o in self.observations)


@dataclass(frozen=True, slots=True)
class Trace:
    conversation_id: str
    source: str
    turns: tuple[Turn, ...]

    def __iter__(self) -> Iterator[Observation]:
        for turn in self.turns:
            yield from turn.observations

    @property
    def observations(self) -> tuple[Observation, ...]:
        return tuple(self)

    def of_kind(self, *kinds: ObservationKind) -> tuple[Observation, ...]:
        return tuple(o for o in self if o.kind in kinds)

    def as_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "source": self.source,
            "turns": [
                {
                    "index": turn.index,
                    "name": turn.name,
                    "observations": [o.as_dict() for o in turn.observations],
                }
                for turn in self.turns
            ],
        }
