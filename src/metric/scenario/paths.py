"""Enumerating the journeys the graph says are possible.

This is the one part of the old Scenario Generator worth keeping almost as it was: a
bounded walk over states and decision outcomes, plus a second pass that goes back for
every edge the walk missed. Two changes.

**Revisit limits come from the policy, not from the enumerator.** The old code used a
decision's `max_attempts` as a DFS loop bound, which meant the limit shaped the test
space and was never itself tested. Here the same threshold does both jobs: it bounds
the walk *and* compiles to a `count_limit` assertion, so "at most three attempts" is a
claim about the agent rather than a property of our search.

**Truncation is an output.** Hitting the path budget is reported as a coverage gap
with the budget that caused it. A generator that silently stops at a thousand paths is
telling you it covered the graph when it covered a prefix of it.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from metric.graph.model import Graph
from metric.ontology.canonical import as_number
from metric.ontology.ids import assertion_id

DEFAULT_MAX_DEPTH = 12
DEFAULT_MAX_PATHS = 500
DEFAULT_MAX_REVISITS = 3


@dataclass(frozen=True, slots=True)
class Step:
    state: str
    decision: str
    outcome: str
    next_state: str

    @property
    def entities(self) -> tuple[str, ...]:
        return tuple(x for x in (self.state, self.decision, self.outcome, self.next_state) if x)


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    entry: str
    steps: tuple[Step, ...]
    terminal: str
    category: str
    complete: bool
    origin: str

    @property
    def entities(self) -> tuple[str, ...]:
        seen = [self.entry]
        for step in self.steps:
            seen.extend(e for e in step.entities if e not in seen)
        return tuple(seen)

    @property
    def length(self) -> int:
        return len(self.steps)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "entry": self.entry,
            "terminal": self.terminal,
            "category": self.category,
            "complete": self.complete,
            "origin": self.origin,
            "steps": [
                {
                    "state": s.state,
                    "decision": s.decision,
                    "outcome": s.outcome,
                    "next_state": s.next_state,
                }
                for s in self.steps
            ],
        }


@dataclass(frozen=True, slots=True)
class ScenarioSpace:
    scenarios: tuple[Scenario, ...]
    truncated: bool
    uncovered: tuple[tuple[str, str, str], ...]
    unreachable: tuple[str, ...]
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenarios": [s.as_dict() for s in self.scenarios],
            "truncated": self.truncated,
            "uncovered": [list(edge) for edge in self.uncovered],
            "unreachable": list(self.unreachable),
            "notes": list(self.notes),
        }


class Journey:
    """The graph read as a state machine: successors, terminals and revisit limits."""

    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self.terminals = frozenset(
            t.head for t in graph.by_relation("IS_TERMINAL") if t.tail.strip().lower() == "true"
        )
        self.edges = _edges(graph)
        self._limits = _revisit_limits(graph, self.edges)

    def successors(self, state: str) -> tuple[tuple[str, str, str], ...]:
        """`(decision, outcome, next_state)` triples leaving a state, decision first."""
        return self.edges.get(state, ())

    def entries(self) -> tuple[str, ...]:
        declared = tuple(sorted({t.tail for t in self.graph.by_relation("STARTS_AT")}))
        if declared:
            return declared

        states = set(self.graph.ids_of_type("State"))
        reached = {edge[2] for edges in self.edges.values() for edge in edges}
        return tuple(sorted(states - reached)) or tuple(sorted(states))

    def limit(self, state: str) -> int:
        return self._limits.get(state, DEFAULT_MAX_REVISITS)

    def category(self, state: str) -> str:
        declared = self.graph.out(state, "HAS_OUTCOME_TYPE")
        return declared[0].tail if declared else ""


def enumerate_scenarios(
    graph: Graph,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_paths: int = DEFAULT_MAX_PATHS,
) -> ScenarioSpace:
    journey = Journey(graph)
    entries = journey.entries()
    notes: list[str] = []

    if not entries:
        return ScenarioSpace((), False, (), (), ("the graph declares no states to start from",))
    if not graph.by_relation("STARTS_AT"):
        notes.append(
            "no STARTS_AT in the graph; entry states were taken to be those nothing leads to"
        )

    scenarios: list[Scenario] = []
    covered: set[tuple[str, str, str]] = set()
    truncated = False

    for entry in entries:
        found, hit_budget = _walk(
            journey, entry, max_depth=max_depth, budget=max_paths - len(scenarios)
        )
        truncated = truncated or hit_budget
        scenarios.extend(found)
        for scenario in found:
            covered.update((s.state, s.decision, s.outcome) for s in scenario.steps)
        if len(scenarios) >= max_paths:
            truncated = True
            break

    all_edges = {
        (state, decision, outcome)
        for state, edges in journey.edges.items()
        for decision, outcome, _ in edges
    }
    uncovered = sorted(all_edges - covered)
    if uncovered:
        scenarios.extend(_reach_for(journey, entries, uncovered, max_depth=max_depth))
        covered.update((s.state, s.decision, s.outcome) for sc in scenarios for s in sc.steps)
        uncovered = sorted(all_edges - covered)

    if truncated:
        notes.append(
            f"enumeration stopped at {max_paths} paths; the space is larger than this and "
            "the scenarios below are a prefix of it, not a cover"
        )

    return ScenarioSpace(
        scenarios=tuple(scenarios),
        truncated=truncated,
        uncovered=tuple(uncovered),
        unreachable=_unreachable(graph, journey, scenarios),
        notes=tuple(notes),
    )


def _walk(
    journey: Journey, entry: str, *, max_depth: int, budget: int
) -> tuple[list[Scenario], bool]:
    scenarios: list[Scenario] = []
    stack: list[tuple[str, tuple[Step, ...], dict[str, int]]] = [(entry, (), {entry: 1})]
    truncated = False

    while stack:
        if len(scenarios) >= budget:
            return scenarios, True

        state, steps, visits = stack.pop()
        successors = journey.successors(state)

        if state in journey.terminals or not successors or len(steps) >= max_depth:
            scenarios.append(_scenario(journey, entry, steps, state, origin="path"))
            if len(steps) >= max_depth and state not in journey.terminals and successors:
                truncated = True
            continue

        for decision, outcome, next_state in reversed(successors):
            seen = visits.get(next_state, 0)
            if seen >= journey.limit(next_state):
                continue
            stack.append(
                (
                    next_state,
                    (*steps, Step(state, decision, outcome, next_state)),
                    {**visits, next_state: seen + 1},
                )
            )

    return scenarios, truncated


def _reach_for(
    journey: Journey,
    entries: tuple[str, ...],
    uncovered: list[tuple[str, str, str]],
    *,
    max_depth: int,
) -> list[Scenario]:
    """One focused path per edge the walk missed.

    A budget-truncated walk leaves real branches untested, and the branches it leaves
    are the deep ones — retries, fallbacks, escalations — which is exactly the wrong
    half to lose.
    """
    found: list[Scenario] = []
    for state, decision, outcome in uncovered:
        prefix = _shortest_path(journey, entries, state, max_depth=max_depth)
        if prefix is None:
            continue
        edge = next(
            (e for e in journey.successors(state) if (e[0], e[1]) == (decision, outcome)), None
        )
        if edge is None:
            continue
        steps = (*prefix, Step(state, decision, outcome, edge[2]))
        found.append(_scenario(journey, steps[0].state, steps, edge[2], origin="edge-gap"))
    return found


def _shortest_path(
    journey: Journey, entries: tuple[str, ...], target: str, *, max_depth: int
) -> tuple[Step, ...] | None:
    queue: deque[tuple[str, tuple[Step, ...]]] = deque((entry, ()) for entry in entries)
    seen = set(entries)

    while queue:
        state, steps = queue.popleft()
        if state == target:
            return steps
        if len(steps) >= max_depth:
            continue
        for decision, outcome, next_state in journey.successors(state):
            if next_state in seen:
                continue
            seen.add(next_state)
            queue.append((next_state, (*steps, Step(state, decision, outcome, next_state))))
    return None


def _scenario(
    journey: Journey, entry: str, steps: tuple[Step, ...], terminal: str, *, origin: str
) -> Scenario:
    return Scenario(
        id=assertion_id("scenario", entry, *(f"{s.decision}:{s.outcome}" for s in steps), terminal),
        entry=entry,
        steps=steps,
        terminal=terminal,
        category=journey.category(terminal),
        complete=terminal in journey.terminals,
        origin=origin,
    )


def _edges(graph: Graph) -> dict[str, tuple[tuple[str, str, str], ...]]:
    edges: dict[str, list[tuple[str, str, str]]] = {}

    for offer in graph.by_relation("OFFERS_DECISION"):
        for has_outcome in graph.out(offer.tail, "HAS_OUTCOME"):
            for leads in graph.out(has_outcome.tail, "LEADS_TO"):
                edges.setdefault(offer.head, []).append(
                    (offer.tail, has_outcome.tail, leads.tail)
                )

    for step in graph.by_relation("HAS_NEXT_STEP"):
        edges.setdefault(step.head, []).append(("", "", step.tail))

    return {state: tuple(sorted(set(found))) for state, found in edges.items()}


def _revisit_limits(
    graph: Graph, edges: dict[str, tuple[tuple[str, str, str], ...]]
) -> dict[str, int]:
    """How often a state may recur, taken from a declared threshold where there is one.

    A threshold on a decision bounds the states that offer it — "at most three
    attempts" is stated about the retry decision and has to bite on the retry state.
    """
    declared: dict[str, int] = {}
    for threshold in graph.by_relation("HAS_THRESHOLD"):
        literal = graph.out(threshold.tail, "VALUE_IS")
        if not literal:
            continue
        number = as_number(literal[0].tail)
        if number is not None and number > 0:
            declared[threshold.head] = number

    limits = {state: value for state, value in declared.items() if state in edges}
    for state, leaving in edges.items():
        for decision, _, _ in leaving:
            if decision in declared:
                limits[state] = min(limits.get(state, declared[decision]), declared[decision])
    return limits


def _unreachable(graph: Graph, journey: Journey, scenarios: list[Scenario]) -> tuple[str, ...]:
    visited = {entity for scenario in scenarios for entity in scenario.entities}
    states = set(graph.ids_of_type("State"))
    return tuple(sorted(states - visited))
