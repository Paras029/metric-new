"""Ground truth for a turn: given a conversation, what did policy require *here*?

This is the reverse direction at the granularity that makes it useful. A contract for
a whole conversation answers "did this run comply?". It does not answer "at turn three,
what should have happened next?" — and that second question is the one a reviewer, a
failure analysis and a regression suite all actually ask.

The shape is the same every time. Bind the turn to a state; the graph then says, from
that state alone:

- which tools belong here (`USES_TOOL`)
- which outcomes those tools may return (`RETURNS`)
- where the conversation may go next (`HAS_NEXT_STEP`, and `LEADS_TO` from each outcome)
- which rules are in force (`GOVERNED_BY`)
- what must be said verbatim (`HAS_TURN` → `HAS_CANONICAL_TEXT`)
- whether this is an ending (`IS_TERMINAL`)

That is the ground truth. Comparing it to what the turn actually did gives the findings,
and the same graph traversal serves a generated scenario and a production conversation —
which is the property that stops the benchmark drifting from the thing it benchmarks.

**A turn whose state was not stated by the agent cannot fail it.** Inference is good
enough to analyse with and not good enough to accuse with, so every assertion on an
uncertain turn is forced to advisory and says why.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Any

from metric.contract.compile import Compiled, compile_all
from metric.contract.model import Assertion, Contract
from metric.graph.model import Graph
from metric.ontology.ids import assertion_id
from metric.ontology.schema import Schema
from metric.trace.binding import BoundTrace
from metric.trace.states import StateBinding, bind_states


@dataclass(frozen=True, slots=True)
class Expected:
    """What the graph says about the states a turn passed through."""

    states: tuple[str, ...]
    tools: tuple[str, ...]
    outcomes: tuple[str, ...]
    next_states: tuple[str, ...]
    rules: tuple[str, ...]
    required_text: tuple[str, ...]
    terminal: bool

    @property
    def state(self) -> str | None:
        return self.states[0] if self.states else None

    @property
    def exit_state(self) -> str | None:
        return self.states[-1] if self.states else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "states": list(self.states),
            "tools": list(self.tools),
            "outcomes": list(self.outcomes),
            "next_states": list(self.next_states),
            "rules": list(self.rules),
            "required_text": list(self.required_text),
            "terminal": self.terminal,
        }


@dataclass(frozen=True, slots=True)
class Observed:
    """What the turn actually did."""

    tools: tuple[str, ...]
    outcomes: tuple[str, ...]
    said: str
    heard: str
    silent: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "tools": list(self.tools),
            "outcomes": list(self.outcomes),
            "said": self.said,
            "heard": self.heard,
            "silent": self.silent,
        }


@dataclass(frozen=True, slots=True)
class TurnTruth:
    turn: int
    binding: StateBinding
    expected: Expected
    observed: Observed
    contract: Contract
    findings: tuple[str, ...]

    @property
    def gradable(self) -> bool:
        return self.binding.certain and bool(self.expected.states)

    def as_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "binding": self.binding.as_dict(),
            "expected": self.expected.as_dict(),
            "observed": self.observed.as_dict(),
            "findings": list(self.findings),
            "gradable": self.gradable,
            "assertions": [a.as_dict() for a in self.contract.assertions],
        }


def expected_at(graph: Graph, states: Sequence[str]) -> Expected:
    """Everything the graph knows about the states a turn passed through.

    Taken over all of them, not just the first. A turn that moves from one state to the
    next legitimately calls the tools of both, and judging it against only the entry
    state reports the second half as unexpected.
    """
    if not states:
        return Expected((), (), (), (), (), (), False)

    tools = tuple(sorted({t.tail for s in states for t in graph.out(s, "USES_TOOL")}))
    outcomes = tuple(sorted({r.tail for tool in tools for r in graph.out(tool, "RETURNS")}))

    exit_state = states[-1]
    next_states = {t.tail for t in graph.out(exit_state, "HAS_NEXT_STEP")}
    for decision in graph.out(exit_state, "OFFERS_DECISION"):
        for outcome in graph.out(decision.tail, "HAS_OUTCOME"):
            next_states.update(t.tail for t in graph.out(outcome.tail, "LEADS_TO"))

    required = tuple(
        sorted(
            text.tail
            for s in states
            for turn in graph.out(s, "HAS_TURN")
            for text in graph.out(turn.tail, "HAS_CANONICAL_TEXT")
        )
    )
    terminal = any(
        t.tail.strip().lower() == "true" for t in graph.out(exit_state, "IS_TERMINAL")
    )

    return Expected(
        states=tuple(states),
        tools=tools,
        outcomes=outcomes,
        next_states=tuple(sorted(next_states)),
        rules=tuple(sorted({t.tail for s in states for t in graph.out(s, "GOVERNED_BY")})),
        required_text=required,
        terminal=terminal,
    )


def resolve_turns(
    graph: Graph,
    schema: Schema,
    bound: BoundTrace,
    *,
    identity: str,
    compiled: Compiled | None = None,
) -> tuple[TurnTruth, ...]:
    """Ground truth for every turn of a conversation."""
    prepared = compiled or compile_all(graph, schema)
    bindings = bind_states(bound, graph)
    truths: list[TurnTruth] = []

    for position, binding in enumerate(bindings):
        following = next(
            (b.state for b in bindings[position + 1 :] if b.state is not None), None
        )
        truths.append(_turn(graph, bound, binding, prepared, identity, following))

    return tuple(truths)


def _turn(
    graph: Graph,
    bound: BoundTrace,
    binding: StateBinding,
    prepared: Compiled,
    identity: str,
    following: str | None,
) -> TurnTruth:
    expected = expected_at(graph, binding.states)
    observed = _observed(bound, binding.turn)
    scope = _scope(expected)

    assertions = prepared.narrow(scope) if scope else ()
    if not binding.certain:
        assertions = tuple(_advisory(a, binding) for a in assertions)

    return TurnTruth(
        turn=binding.turn,
        binding=binding,
        expected=expected,
        observed=observed,
        contract=Contract(
            id=assertion_id("turn", identity, str(binding.turn)),
            binding=f"turn:{binding.turn}",
            identity=identity,
            assertions=assertions,
            notes=prepared.notes,
        ),
        findings=_findings(graph, expected, observed, binding, following),
    )


def _scope(expected: Expected) -> tuple[str, ...]:
    if not expected.states:
        return ()
    return (
        *expected.states,
        *expected.tools,
        *expected.outcomes,
        *expected.next_states,
        *expected.rules,
    )


def _observed(bound: BoundTrace, turn: int) -> Observed:
    here = [b for b in bound.bindings if b.observation.turn == turn]
    return Observed(
        tools=tuple(b.entity for b in here if b.entity_type == "Tool" and b.entity),
        outcomes=tuple(b.entity for b in here if b.entity_type == "Outcome" and b.entity),
        said=" ".join(b.observation.value for b in here if b.observation.kind == "assistant"),
        heard=" ".join(b.observation.value for b in here if b.observation.kind == "utterance"),
        silent=any(b.observation.kind == "silence" for b in here),
    )


def _findings(
    graph: Graph,
    expected: Expected,
    observed: Observed,
    binding: StateBinding,
    following: str | None,
) -> tuple[str, ...]:
    """The direct comparison: what the graph said here, against what the turn did."""
    if not expected.states:
        return ("this turn could not be placed in the graph, so nothing can be said about it",)

    found: list[str] = []
    name = graph.label

    where = " or ".join(name(s) for s in expected.states)
    unexpected = [t for t in observed.tools if t not in expected.tools]
    if unexpected:
        found.append(
            f"called {', '.join(sorted(name(t) for t in unexpected))}, which "
            f"{where} does not declare"
        )

    stray = [o for o in observed.outcomes if expected.outcomes and o not in expected.outcomes]
    if stray:
        found.append(
            f"got {', '.join(sorted(name(o) for o in stray))}, which no tool here declares"
        )

    hops = _hops(graph, expected.states, following)
    for source, target in hops:
        allowed = _successors(graph, source)
        if allowed and target not in allowed:
            found.append(f"moved from {name(source)} to {name(target)}, which does not follow it")

    ending = expected.exit_state
    if expected.terminal and following is not None and ending is not None:
        found.append(f"{name(ending)} ends the journey but the run continued")

    for text in expected.required_text:
        if text and _folded(text) not in _folded(observed.said):
            found.append(f"did not say the required wording: {text[:60]}")

    # Only where the state has tools to call. A state whose whole job is to speak —
    # an opening, a retry prompt — is *supposed* to produce no tool call, and reporting
    # that as a finding fired on every clean run of the reference agent.
    if observed.silent and not expected.terminal and expected.tools:
        found.append(
            f"the turn produced no tool call, and {where} declares "
            f"{', '.join(sorted(name(t) for t in expected.tools))}"
        )

    return tuple(found)


def _hops(graph: Graph, states: Sequence[str], following: str | None) -> list[tuple[str, str]]:
    """Every transition this turn made, including the one out of it."""
    walk = [*states, following] if following is not None else list(states)
    return [(a, b) for a, b in pairwise(walk) if a != b]


def _successors(graph: Graph, state: str) -> set[str]:
    allowed = {t.tail for t in graph.out(state, "HAS_NEXT_STEP")}
    for decision in graph.out(state, "OFFERS_DECISION"):
        for outcome in graph.out(decision.tail, "HAS_OUTCOME"):
            allowed.update(t.tail for t in graph.out(outcome.tail, "LEADS_TO"))
    return allowed


def _advisory(assertion: Assertion, binding: StateBinding) -> Assertion:
    return replace(
        assertion,
        severity="advisory",
        provisional=True,
        note=(
            f"the state here was {binding.method}, not stated by the agent, so this "
            "cannot fail it"
        ),
    )


def _folded(text: str) -> str:
    return " ".join(text.split()).casefold()
