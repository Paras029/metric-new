"""What a trace says the agent is, as distinct from what policy says it should be.

This is the reverse direction: instead of reading a document to learn what should
happen, read traces to learn what does. It exists because the ontology and the traces
we have are for different agents, and writing a policy document from telemetry would
be fabricating policy. Discovery does the honest half — it recovers the *structure* an
agent demonstrably has — and leaves the obligations to a person who can read the real
procedure.

**Observed is not normative, and the distinction has to survive into the graph.** A
rule derived from watching an agent cannot be used to fail that agent; it would pass by
construction. Everything discovered here carries `telemetry` as its method, and the
contract compiler refuses to let a telemetry-only assertion block. What discovery is
good for is binding, coverage, and showing a reviewer the shape of the thing before
they write a line of policy.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from metric.trace.model import Trace

_BOOLEAN = frozenset({"true", "false", ""})
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")


@dataclass(slots=True)
class Observed:
    """Everything one or more traces demonstrate about an agent's structure."""

    capabilities: Counter[str] = field(default_factory=Counter)
    tools: Counter[str] = field(default_factory=Counter)
    outcomes: dict[str, set[str]] = field(default_factory=dict)
    written: dict[str, set[str]] = field(default_factory=dict)
    arguments: dict[str, set[str]] = field(default_factory=dict)
    transitions: dict[str, Counter[str]] = field(default_factory=dict)
    first_seen: dict[str, str] = field(default_factory=dict)
    traces: list[str] = field(default_factory=list)

    @property
    def variables(self) -> dict[str, set[str]]:
        merged = {name: set(values) for name, values in self.arguments.items()}
        for name, values in self.written.items():
            merged.setdefault(name, set()).update(values)
        return merged

    @property
    def checkpoint_candidates(self) -> list[str]:
        """Variables the agent explicitly writes, whose values look like places.

        Only explicit writes count. A tool argument carrying a counter is state too,
        but it is state the agent was *given*; a `set_metadata` write is the agent
        saying where it has got to, and that is the only thing a journey can be read
        from. Values that are numbers or booleans are counters and flags, not places.

        A variable seen with one value still counts — a short trace may simply not have
        moved yet, and excluding it would mean no single conversation could ever reveal
        the journey.
        """
        ranked = [
            (name, len(values))
            for name, values in self.written.items()
            if values and all(_symbolic(v) for v in values)
        ]
        ranked.sort(key=lambda pair: (-pair[1], pair[0]))
        return [name for name, _ in ranked]

    def checkpoint_variable(self) -> str:
        """The best candidate, preferring one that says what it is."""
        candidates = self.checkpoint_candidates
        named = [c for c in candidates if "checkpoint" in c.lower() or "state" in c.lower()]
        return (named or candidates or [""])[0]

    def states(self, variable: str) -> list[str]:
        return sorted(self.variables.get(variable, set()))

    def as_dict(self) -> dict[str, Any]:
        return {
            "traces": list(self.traces),
            "capabilities": dict(self.capabilities),
            "tools": dict(self.tools),
            "outcomes": {k: sorted(v) for k, v in sorted(self.outcomes.items())},
            "written": {k: sorted(v) for k, v in sorted(self.written.items())},
            "arguments": {k: sorted(v) for k, v in sorted(self.arguments.items())},
            "checkpoint_candidates": self.checkpoint_candidates,
        }


def observe(traces: list[Trace]) -> Observed:
    found = Observed()
    for trace in traces:
        found.traces.append(trace.conversation_id)
        _read(found, trace)
    return found


def _read(found: Observed, trace: Trace) -> None:
    last_tool = ""
    previous: dict[str, str] = {}

    for observation in trace.observations:
        found.first_seen.setdefault(observation.name, observation.ref)

        if observation.kind == "capability":
            found.capabilities[observation.name] += 1

        elif observation.kind == "tool_call":
            found.tools[observation.name] += 1
            last_tool = observation.name
            for name, value in observation.arguments:
                found.arguments.setdefault(name, set()).add(value)

        elif observation.kind == "outcome":
            found.outcomes.setdefault(observation.value, set()).add(observation.name or last_tool)

        elif observation.kind == "state_write":
            found.written.setdefault(observation.name, set()).add(observation.value)
            # A second write to the same variable is a transition out of the first value.
            earlier = previous.get(observation.name)
            if earlier is not None and earlier != observation.value:
                found.transitions.setdefault(earlier, Counter())[observation.value] += 1
            previous[observation.name] = observation.value


def _symbolic(value: str) -> bool:
    lowered = value.strip().lower()
    return bool(lowered) and lowered not in _BOOLEAN and not _NUMBER.match(lowered)
