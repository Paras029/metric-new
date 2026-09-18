"""Runtime state, replayed from what the trace showed.

The old Scenario Generator had no runtime state at all: a path was a sequence of
labels, and `max_attempts` was a loop bound on the enumerator rather than a claim
about the agent. Nothing could be checked because there was nothing to check against.

This is the missing half. Replaying a bound trace gives the variable values, the peaks
those variables reached and the order things happened in — which is exactly what a
count limit, a transition and an ordering constraint need in order to be gradable.

Two carriers, with different authority. A `set_metadata` write is the agent asserting
a value. A tool argument is the value the agent *passed*, which is equally observed
but incidental — so writes are applied after arguments at the same step, and the
distinction is kept so a reviewer can see which one a verdict rests on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from metric.ontology.canonical import as_number
from metric.trace.binding import BoundTrace, Lexicon


@dataclass(frozen=True, slots=True)
class Write:
    """One observed assignment, kept for evidence."""

    ref: str
    turn: int
    step: int
    variable: str
    entity: str | None
    value: str
    source: str  # "state_write" | "tool_argument"


@dataclass(slots=True)
class RuntimeContext:
    """The state of the run, keyed by entity id where binding succeeded.

    `unbound` holds variables the ontology does not know. They are shown, never
    graded: an assertion resting on a variable nobody declared would be an assertion
    about a name, not about behaviour.
    """

    variables: dict[str, str] = field(default_factory=dict)
    unbound: dict[str, str] = field(default_factory=dict)
    peaks: dict[str, int] = field(default_factory=dict)
    tool_calls: dict[str, int] = field(default_factory=dict)
    sequence: list[str] = field(default_factory=list)
    history: list[Write] = field(default_factory=list)

    def value(self, variable: str) -> str | None:
        return self.variables.get(variable)

    def peak(self, variable: str) -> int | None:
        return self.peaks.get(variable)

    def calls(self, tool: str) -> int:
        return self.tool_calls.get(tool, 0)

    def precedes(self, first: str, second: str) -> bool | None:
        """Whether `first` was observed before `second`. None if either never was."""
        if first not in self.sequence or second not in self.sequence:
            return None
        return self.sequence.index(first) < self.sequence.index(second)

    def as_dict(self) -> dict[str, Any]:
        return {
            "variables": dict(sorted(self.variables.items())),
            "unbound": dict(sorted(self.unbound.items())),
            "peaks": dict(sorted(self.peaks.items())),
            "tool_calls": dict(sorted(self.tool_calls.items())),
            "sequence": list(self.sequence),
        }


def replay(bound: BoundTrace, lexicon: Lexicon) -> RuntimeContext:
    context = RuntimeContext()

    for binding in bound.bindings:
        observation = binding.observation

        if observation.kind == "tool_call":
            if binding.entity is not None:
                context.tool_calls[binding.entity] = context.calls(binding.entity) + 1
                context.sequence.append(binding.entity)
            for name, value in observation.arguments:
                _record(context, lexicon, observation, name, value, source="tool_argument")

        elif observation.kind == "state_write" and binding.entity_type == "StateVariable":
            _record(
                context,
                lexicon,
                observation,
                observation.name,
                observation.value,
                source="state_write",
                entity=binding.entity,
            )

        elif binding.entity is not None and binding.entity_type in {"Outcome", "State"}:
            context.sequence.append(binding.entity)

    return context


def _record(
    context: RuntimeContext,
    lexicon: Lexicon,
    observation: Any,
    name: str,
    value: str,
    *,
    source: str,
    entity: str | None = None,
) -> None:
    if entity is None:
        entity, _ = lexicon.look_up("StateVariable", name)

    if value != "":
        if entity is not None:
            context.variables[entity] = value
        else:
            context.unbound[name] = value

    number = as_number(value)
    if number is not None:
        key = entity or name
        context.peaks[key] = max(context.peaks.get(key, number), number)

    context.history.append(
        Write(
            ref=observation.ref,
            turn=observation.turn,
            step=observation.step,
            variable=name,
            entity=entity,
            value=value,
            source=source,
        )
    )
