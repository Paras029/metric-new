from __future__ import annotations

from pathlib import Path

from metric.runtime.context import replay
from metric.trace.binding import Lexicon, bind
from metric.trace.galileo import read_galileo_export

REPO = Path(__file__).resolve().parents[1]
PRODUCTION = REPO / "grounding" / "03-otel-trace-sample-galileo.json"
DEMO = REPO / "fixtures" / "card_auth.trace.json"


class TestGalileoReader:
    def test_the_production_export_reads(self) -> None:
        trace = read_galileo_export(PRODUCTION)
        assert trace.conversation_id == "70871984-b053-4448-9b01-6ca57c3279ea"
        assert len(trace.turns) == 6

    def test_set_metadata_is_read_as_a_state_assignment(self) -> None:
        writes = read_galileo_export(PRODUCTION).of_kind("state_write")
        assert ("checkpoint", "check14Key") in [(w.name, w.value) for w in writes]

    def test_a_symbolic_tool_result_is_an_outcome_and_an_http_code_is_not(self) -> None:
        outcomes = {o.value for o in read_galileo_export(PRODUCTION).of_kind("outcome")}
        assert "NO_USER_RESPONSE" in outcomes
        assert "PROFILE_NO_MATCH" in outcomes, "nested under response.status"
        assert "200" not in outcomes

    def test_tool_arguments_are_kept_including_the_counters(self) -> None:
        calls = read_galileo_export(PRODUCTION).of_kind("tool_call")
        arguments = {k: v for call in calls for k, v in call.arguments}
        assert arguments["no_user_pref_counter"] == "1"

    def test_the_llm_span_is_a_python_repr_and_still_parses(self) -> None:
        said = read_galileo_export(PRODUCTION).of_kind("utterance")
        assert any("Five Centimeters fifteen" in o.value for o in said)

    def test_a_turn_with_no_tool_call_is_an_observation_not_a_parse_failure(self) -> None:
        trace = read_galileo_export(PRODUCTION)
        assert [t.index for t in trace.turns if t.silent] == [4, 5]


class TestBinding:
    def test_a_trace_from_another_agent_binds_to_nothing_and_says_so(self, built) -> None:
        bound = bind(read_galileo_export(PRODUCTION), built.graph)
        assert bound.coverage == 0.0
        assert "check_fullssn_or_cm15" in {b.token for b in bound.unbound}

    def test_the_profile_makes_binding_declared_rather_than_guessed(self, built) -> None:
        bound = bind(
            read_galileo_export(DEMO), built.graph, checkpoint_variable=built.checkpoint_variable
        )
        tools = bound.of_type("Tool")
        assert tools and all(b.method == "declared" for b in tools)
        assert bound.coverage > 0.7

    def test_checkpoint_values_bind_to_states(self, built) -> None:
        bound = bind(
            read_galileo_export(DEMO), built.graph, checkpoint_variable=built.checkpoint_variable
        )
        states = [built.graph.label(e) for e in bound.entities("State")]
        assert states[0] == "Opening and authentication"
        assert states[-1] == "Transfer and end of automated journey"

    def test_a_counter_write_is_not_mistaken_for_a_state(self, built) -> None:
        bound = bind(
            read_galileo_export(DEMO), built.graph, checkpoint_variable=built.checkpoint_variable
        )
        assert not any(b.entity_type == "State" and b.token.isdigit() for b in bound.bindings)


class TestRuntimeReplay:
    def test_tool_calls_and_counter_peaks_are_recovered(self, built) -> None:
        lexicon = Lexicon(built.graph, checkpoint_variable=built.checkpoint_variable)
        bound = bind(
            read_galileo_export(DEMO), built.graph, checkpoint_variable=built.checkpoint_variable
        )
        context = replay(bound, lexicon)

        tool = next(e.id for e in built.graph.entities if e.canonical == "authenticate_customer")
        variable = next(
            e.id for e in built.graph.entities if e.canonical == "authentication_attempt_count"
        )
        assert context.calls(tool) == 4
        assert context.peak(variable) == 4

    def test_order_is_answerable_and_says_so_when_it_is_not(self, built) -> None:
        lexicon = Lexicon(built.graph, checkpoint_variable=built.checkpoint_variable)
        bound = bind(
            read_galileo_export(DEMO), built.graph, checkpoint_variable=built.checkpoint_variable
        )
        context = replay(bound, lexicon)
        states = bound.entities("State")
        assert context.precedes(states[0], states[-1]) is True
        assert context.precedes(states[0], "State:nothing") is None
