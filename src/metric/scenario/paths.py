"""The `journey_path` generator: enumerating the routes the graph says are possible.

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

One category of eleven. `space.py` composes it with the rest.
"""

from __future__ import annotations

from collections import deque

from metric.graph.journey import Journey
from metric.graph.model import Graph
from metric.ontology.ids import assertion_id
from metric.scenario.model import Scenario, ScenarioSpace, Step

DEFAULT_MAX_DEPTH = 12
DEFAULT_MAX_PATHS = 500


def enumerate_scenarios(
    graph: Graph,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_paths: int = DEFAULT_MAX_PATHS,
    journey: Journey | None = None,
    reach_for_uncovered: bool = True,
) -> ScenarioSpace:
    walk = journey or Journey(graph)
    entries = walk.entries()
    notes: list[str] = []

    if not entries:
        return ScenarioSpace((), notes=("the graph declares no states to start from",))
    if not graph.by_relation("STARTS_AT"):
        notes.append(
            "no STARTS_AT in the graph; entry states were taken to be those nothing leads to"
        )

    scenarios: list[Scenario] = []
    covered: set[tuple[str, str, str]] = set()
    truncated = False

    for entry in entries:
        found, hit_budget = _walk(
            walk, entry, max_depth=max_depth, budget=max_paths - len(scenarios)
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
        for state, edges in walk.edges.items()
        for decision, outcome, _ in edges
    }
    uncovered = sorted(all_edges - covered)
    if uncovered and reach_for_uncovered:
        scenarios.extend(_reach_for(walk, entries, uncovered, max_depth=max_depth))
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
        unreachable=_unreachable(graph, scenarios),
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
    label = journey.graph.label
    route = " → ".join([label(entry), *(label(s.next_state) for s in steps)])
    return Scenario(
        id=assertion_id("scenario", entry, *(f"{s.decision}:{s.outcome}" for s in steps), terminal),
        category="journey_path",
        family="traversal",
        answer_type="path",
        question=f"Walk {route}",
        answer=tuple([entry, *(s.next_state for s in steps)]),
        entry=entry,
        steps=steps,
        terminal=terminal,
        ends_as=journey.ends_as(terminal),
        complete=terminal in journey.terminals,
        origin=origin,
    )


def _unreachable(graph: Graph, scenarios: list[Scenario]) -> tuple[str, ...]:
    visited = {entity for scenario in scenarios for entity in scenario.entities}
    states = set(graph.ids_of_type("State"))
    return tuple(sorted(states - visited))
