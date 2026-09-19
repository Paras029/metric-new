from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from metric.discover.emit import (
    ObservationError,
    apply_observations,
    load_observations,
    observation_yaml,
    profile_yaml,
)
from metric.discover.observe import observe
from metric.graph.model import build
from metric.telemetry.profile import load_profile
from metric.trace.binding import bind
from metric.trace.galileo import read_galileo_export

REPO = Path(__file__).resolve().parents[1]
PRODUCTION = REPO / "grounding" / "03-otel-trace-sample-galileo.json"


@pytest.fixture(scope="module")
def found():
    return observe([read_galileo_export(PRODUCTION)])


class TestObserving:
    def test_tools_and_outcomes_come_out_of_a_real_export(self, found) -> None:
        assert "check_fullssn_or_cm15" in found.tools
        assert found.outcomes["PROFILE_NO_MATCH"] == {"check_ANI"}

    def test_an_explicit_write_is_a_checkpoint_candidate_and_an_argument_is_not(
        self, found
    ) -> None:
        assert "checkpoint" in found.checkpoint_candidates
        assert "no_user_pref_counter" in found.arguments
        assert "no_user_pref_counter" not in found.checkpoint_candidates

    def test_counters_and_flags_are_not_mistaken_for_places(self, found) -> None:
        assert "check_fullssn_or_cm15_called" not in found.checkpoint_candidates

    def test_one_short_trace_still_reveals_the_journey_variable(self, found) -> None:
        assert found.checkpoint_variable() == "checkpoint"
        assert found.states("checkpoint") == ["check14Key"]


class TestEmitting:
    def test_the_profile_maps_every_observed_name_to_itself(self, found) -> None:
        document = yaml.safe_load(profile_yaml(found, name="x", use_case="X"))
        assert document["tools"]["check_ANI"] == "check_ANI"
        assert document["checkpoint_variable"] == "checkpoint"

    def test_the_profile_names_the_candidates_it_did_not_pick(self, found) -> None:
        assert "checkpoint_14key" in profile_yaml(found, name="x", use_case="X")

    def test_the_observation_file_says_it_is_not_policy(self, found) -> None:
        text = observation_yaml(found, name="x", use_case="X")
        assert "not what policy" in text

    def test_a_file_with_no_use_case_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("version: 1\ntools: []\n", encoding="utf-8")
        with pytest.raises(ObservationError, match="no use_case"):
            load_observations(path)


class TestApplying:
    def test_observed_facts_carry_telemetry_as_their_method(self) -> None:
        document = load_observations(REPO / "observed" / "aop.observed.yaml")
        graph = apply_observations(build([], []), document)
        assert graph.triples
        assert all(t.methods == {"telemetry"} for t in graph.triples)

    def test_evidence_points_at_the_trace_not_a_document(self) -> None:
        document = load_observations(REPO / "observed" / "aop.observed.yaml")
        graph = apply_observations(build([], []), document)
        spans = [s for t in graph.triples for s in t.spans]
        assert all(s.passage_id.startswith("observed:") for s in spans)
        assert any("turn" in s.quote for s in spans)

    def test_the_discovered_graph_binds_the_trace_it_came_from(self) -> None:
        document = load_observations(REPO / "observed" / "aop.observed.yaml")
        graph = apply_observations(build([], []), document)
        profile = load_profile(REPO / "profiles" / "aop.telemetry.yaml")
        bound = bind(
            read_galileo_export(PRODUCTION),
            graph,
            checkpoint_variable=profile.checkpoint_variable,
        )
        assert bound.coverage > 0.9


class TestObservedCannotGrade:
    def test_nothing_learned_from_an_agent_can_fail_it(self, aop) -> None:
        evaluation = aop.evaluations[0]
        assert evaluation.verdicts
        assert not evaluation.blocked
        assert all(v.assertion.severity == "advisory" for v in evaluation.verdicts)

    def test_and_it_says_why(self, aop) -> None:
        notes = {v.assertion.note for v in aop.evaluations[0].verdicts}
        assert any("passes by construction" in note for note in notes)

    def test_the_build_is_reproducible(self, aop) -> None:
        import json

        from metric.workspace import BuildSpec, Workspace

        again = Workspace(BuildSpec.from_corpus(REPO / "corpus-aop.yaml", out_dir=aop.spec.out_dir))
        assert json.dumps(aop.graph.as_dict(), sort_keys=True) == json.dumps(
            again.graph.as_dict(), sort_keys=True
        )
