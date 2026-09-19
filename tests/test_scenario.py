from __future__ import annotations

from itertools import pairwise

from tests.conftest import entity, triple

from metric.graph.model import build as build_graph
from metric.scenario.paths import enumerate_scenarios


def line(length: int) -> tuple:
    """A straight chain of states ending in a terminal."""
    states = [f"State:s{i}" for i in range(length)]
    entities = [entity(s, "State") for s in states]
    triples = [triple("UseCase:u", "STARTS_AT", states[0])]
    triples += [triple(a, "HAS_NEXT_STEP", b) for a, b in pairwise(states)]
    triples.append(triple(states[-1], "IS_TERMINAL", "true", kind="literal"))
    return build_graph([*entities, entity("UseCase:u", "UseCase")], triples)


class TestEnumeration:
    def test_a_straight_journey_is_one_scenario(self) -> None:
        space = enumerate_scenarios(line(4))
        assert len(space.scenarios) == 1
        assert space.scenarios[0].complete
        assert not space.truncated

    def test_entry_states_are_inferred_when_none_are_declared(self) -> None:
        graph = build_graph(
            [entity("State:a", "State"), entity("State:b", "State")],
            [triple("State:a", "HAS_NEXT_STEP", "State:b")],
        )
        space = enumerate_scenarios(graph)
        assert space.scenarios[0].entry == "State:a"
        assert any("STARTS_AT" in note for note in space.notes)

    def test_the_real_policy_covers_every_branch(self, built) -> None:
        space = built.space
        assert len(space.scenarios) >= 4
        assert space.uncovered == ()
        assert space.unreachable == ()

    def test_a_retry_loop_is_bounded_by_the_declared_threshold(self, built) -> None:
        retry = next(
            e.id
            for e in built.graph.entities
            if e.type == "State" and e.canonical == "failed_authentication_and_retry"
        )
        visits = [
            sum(1 for step in s.steps if step.next_state == retry)
            for s in built.space.of_category("journey_path")
        ]
        assert max(visits) == 3, "the policy caps attempts at three, so the walk stops there"

    def test_how_a_journey_ends_comes_from_the_terminal_state_never_a_guess(self, built) -> None:
        journeys = built.space.of_category("journey_path")
        assert {s.ends_as for s in journeys} == {"Termination"}


class TestCoverageIsReported:
    def test_truncation_is_an_output_not_a_silent_stop(self) -> None:
        space = enumerate_scenarios(line(8), max_paths=1, max_depth=3)
        assert space.truncated
        assert any("prefix" in note for note in space.notes)

    def test_an_unreachable_state_is_named(self) -> None:
        graph = build_graph(
            [
                entity("State:a", "State"),
                entity("State:b", "State"),
                entity("State:orphan", "State"),
            ],
            [
                triple("UseCase:u", "STARTS_AT", "State:a"),
                triple("State:a", "HAS_NEXT_STEP", "State:b"),
                triple("State:b", "IS_TERMINAL", "true", kind="literal"),
            ],
        )
        assert "State:orphan" in enumerate_scenarios(graph).unreachable

    def test_a_branch_the_walk_missed_gets_its_own_focused_path(self) -> None:
        graph = build_graph(
            [
                entity("State:a", "State"),
                entity("State:b", "State"),
                entity("Decision:d", "Decision"),
                entity("Outcome:x", "Outcome"),
                entity("Outcome:y", "Outcome"),
                entity("State:end", "State"),
            ],
            [
                triple("UseCase:u", "STARTS_AT", "State:a"),
                triple("State:a", "OFFERS_DECISION", "Decision:d"),
                triple("Decision:d", "HAS_OUTCOME", "Outcome:x"),
                triple("Decision:d", "HAS_OUTCOME", "Outcome:y"),
                triple("Outcome:x", "LEADS_TO", "State:b"),
                triple("Outcome:y", "LEADS_TO", "State:end"),
                triple("State:b", "IS_TERMINAL", "true", kind="literal"),
                triple("State:end", "IS_TERMINAL", "true", kind="literal"),
            ],
        )
        space = enumerate_scenarios(graph, max_paths=1)
        assert space.uncovered == ()
        assert any(s.origin == "edge-gap" for s in space.scenarios)
