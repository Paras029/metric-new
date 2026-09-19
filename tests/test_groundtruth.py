"""The reverse direction: conversation and telemetry in, ground truth per turn out."""

from __future__ import annotations

from dataclasses import replace

from metric.groundtruth import expected_at, resolve_turns
from metric.trace.binding import bind
from metric.trace.model import Trace
from metric.trace.states import bind_states


def bound_of(space, index: int = 0):
    return bind(space.traces[index], space.graph, checkpoint_variable=space.checkpoint_variable)


def truths_of(space, index: int = 0):
    return resolve_turns(
        space.graph,
        space.schema,
        bound_of(space, index),
        identity=space.identity,
        compiled=space.compiled,
    )


def without_checkpoints(trace: Trace) -> Trace:
    """The same conversation with the agent saying nothing about where it is."""
    return Trace(
        conversation_id=trace.conversation_id,
        source=trace.source,
        turns=tuple(
            replace(t, observations=tuple(o for o in t.observations if o.kind != "state_write"))
            for t in trace.turns
        ),
    )


class TestWhatTheGraphSaysAtAState:
    def test_a_state_yields_its_tools_outcomes_and_exits(self, built) -> None:
        graph = built.graph
        state = next(
            e.id
            for e in graph.entities
            if e.type == "State" and e.canonical == "authentication_attempts"
        )
        expected = expected_at(graph, [state])

        assert [graph.label(t) for t in expected.tools] == ["authenticate_customer"]
        assert set(graph.label(o) for o in expected.outcomes) == {"AUTHENTICATED", "FAILED"}
        assert expected.next_states
        assert not expected.terminal

    def test_a_terminal_state_says_so_and_offers_no_exit(self, built) -> None:
        graph = built.graph
        state = next(
            e.id
            for e in graph.entities
            if e.type == "State" and e.canonical.startswith("transfer_and_end")
        )
        expected = expected_at(graph, [state])
        assert expected.terminal
        assert expected.next_states == ()

    def test_a_turn_spanning_two_states_takes_both(self, built) -> None:
        graph = built.graph
        states = [
            e.id
            for e in graph.entities
            if e.type == "State"
            and e.canonical in {"authentication_attempts", "failed_authentication_and_retry"}
        ]
        assert len(expected_at(graph, states).tools) >= 1

    def test_an_unplaced_turn_expects_nothing(self, built) -> None:
        assert expected_at(built.graph, []).states == ()


class TestBindingATurnToTheGraph:
    def test_a_checkpoint_is_certain_and_everything_else_is_not(self, built) -> None:
        bindings = bind_states(bound_of(built), built.graph)
        assert all(b.method == "checkpoint" for b in bindings)
        assert all(b.certain and b.confidence == 1.0 for b in bindings)

    def test_a_turn_can_pass_through_several_states(self, built) -> None:
        bindings = bind_states(bound_of(built), built.graph)
        assert any(len(b.states) > 1 for b in bindings), (
            "the agent writes two checkpoints in one turn; collapsing them loses the hop"
        )

    def test_the_binding_says_how_it_was_reached(self, built) -> None:
        for binding in bind_states(bound_of(built), built.graph):
            assert binding.reason
            assert binding.evidence or not binding.states


class TestRecoveringStateWithoutCheckpoints:
    """The inverse mapping, measured against a trace whose answer we know."""

    def test_most_turns_are_recovered_from_behaviour_alone(self, built) -> None:
        graph = built.graph
        answer = {b.turn: b.states for b in bind_states(bound_of(built), graph)}

        blind = bind(
            without_checkpoints(built.traces[0]),
            graph,
            checkpoint_variable=built.checkpoint_variable,
        )
        recovered = bind_states(blind, graph)

        correct = [b for b in recovered if b.states and b.states[0] in answer.get(b.turn, ())]
        assert len(correct) >= len(recovered) - 1, (
            "with no checkpoints at all, tools and outcomes should still place the turns"
        )
        assert all(b.method in {"inferred", "carried", "none"} for b in recovered)

    def test_a_turn_that_did_nothing_is_left_unplaced_rather_than_guessed(self, built) -> None:
        blind = bind(
            without_checkpoints(built.traces[0]),
            built.graph,
            checkpoint_variable=built.checkpoint_variable,
        )
        first = bind_states(blind, built.graph)[0]
        assert first.method == "none"
        assert first.state is None

    def test_an_inferred_turn_cannot_fail_the_agent(self, built) -> None:
        blind = bind(
            without_checkpoints(built.traces[0]),
            built.graph,
            checkpoint_variable=built.checkpoint_variable,
        )
        truths = resolve_turns(
            built.graph, built.schema, blind, identity=built.identity, compiled=built.compiled
        )
        inferred = [t for t in truths if t.binding.method == "inferred"]
        assert inferred
        assert all(not t.gradable for t in inferred)
        assert all(
            a.severity == "advisory" for t in inferred for a in t.contract.assertions
        )
        assert any(
            "not stated by the agent" in a.note for t in inferred for a in t.contract.assertions
        )


class TestGroundTruthPerTurn:
    def test_every_turn_gets_the_assertions_in_force_there(self, built) -> None:
        truths = truths_of(built)
        assert len(truths) == len(built.traces[0].turns)
        assert all(t.contract.assertions for t in truths if t.expected.states)

    def test_a_turn_contract_is_narrower_than_the_conversation_contract(self, built) -> None:
        from metric.resolve import resolve_for_trace

        whole = resolve_for_trace(
            built.graph,
            built.schema,
            bound_of(built),
            identity=built.identity,
            compiled=built.compiled,
        )
        turn = truths_of(built)[0]
        assert len(turn.contract.assertions) < len(whole.assertions)

    def test_a_transition_the_graph_does_not_allow_is_a_finding(self, built) -> None:
        findings = [f for t in truths_of(built) for f in t.findings]
        assert any("does not follow it" in f for f in findings)

    def test_a_turn_doing_what_its_state_declares_raises_nothing(self, built) -> None:
        truths = truths_of(built)
        clean = [t for t in truths if not t.findings]
        assert clean
        for truth in clean:
            assert set(truth.observed.tools) <= set(truth.expected.tools)

    def test_the_evaluation_reports_how_much_it_could_place(self, built) -> None:
        evaluation = built.evaluations[0]
        assert evaluation.turns
        assert evaluation.placed == len(evaluation.turns)
        assert evaluation.certain == len(evaluation.turns)


class TestAnotherAgentsConversation:
    def test_turns_that_cannot_be_placed_say_so(self, built) -> None:
        production = built.evaluations[1]
        assert production.placed == 0
        assert all(
            "could not be placed" in " ".join(t.findings) for t in production.turns
        )
