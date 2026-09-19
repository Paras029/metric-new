"""The graph read as a state machine.

Three things need this reading and they are in different layers: scenario enumeration
walks it forward, the workflow diagram draws it, and the trace binder walks it
*backwards* to work out where a conversation must have been. That last one is why this
lives here rather than under `scenario` — a journey is a property of the graph, not of
the test space derived from it.
"""

from __future__ import annotations

from metric.graph.model import Graph
from metric.ontology.canonical import as_number

DEFAULT_MAX_REVISITS = 3


class Journey:
    """The graph read as a state machine: successors, terminals and revisit limits."""

    def __init__(self, graph: Graph, *, default_revisits: int = DEFAULT_MAX_REVISITS) -> None:
        self.graph = graph
        self.default_revisits = default_revisits
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
        return self._limits.get(state, self.default_revisits)

    def ends_as(self, state: str) -> str:
        """The class of ending a state represents, where the policy declares one."""
        declared = self.graph.out(state, "HAS_OUTCOME_TYPE")
        return declared[0].tail if declared else ""



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
