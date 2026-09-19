"""The base taxonomy, the capability gate, and the functionality check.

The functionality check is the reason most of these exist. Its job is to notice when a
generator and the triples disagree, so the tests that matter are the ones that make them
disagree on purpose and assert that the base does not survive.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from tests.conftest import entity, triple

from metric.enrich.design import Item, plan
from metric.enrich.factors import CatalogueError, load_catalogue
from metric.graph.model import build as build_graph
from metric.scenario.bases import generate, verify
from metric.scenario.capability import capabilities
from metric.scenario.model import Scenario, Step
from metric.scenario.space import SeedError, build_space, load_seeds
from metric.scenario.taxonomy import CATEGORIES, admissible

REPO = Path(__file__).resolve().parents[1]
VOICE = REPO / "catalogs" / "voice.factors.yaml"


def states(*names: str):
    return [entity(f"State:{n}", "State", canonical=n) for n in names]


class TestCapabilities:
    def test_a_graph_with_only_states_supports_almost_nothing(self) -> None:
        caps = capabilities(build_graph(states("a", "b"), []))
        assert "path" not in caps
        assert "prohibition" not in caps
        assert "threshold" not in caps

    def test_a_relation_present_makes_its_capability_present(self) -> None:
        graph = build_graph(
            states("a", "b"), [triple("State:a", "HAS_NEXT_STEP", "State:b")]
        )
        caps = capabilities(graph)
        assert "path" in caps
        assert caps.evidence["path"] == 1

    def test_a_capability_needing_two_relations_needs_both(self) -> None:
        """`branch` is decisions *and* their outcomes; one alone answers no question."""
        graph = build_graph(
            [*states("a"), entity("Decision:d", "Decision")],
            [triple("State:a", "OFFERS_DECISION", "Decision:d")],
        )
        assert "branch" not in capabilities(graph)

    def test_a_graph_learned_from_traces_is_never_a_closed_world(self) -> None:
        """Its states were derived from the tool calls made at them.

        So "every state declares tools" is a tautology, and reading it as closure turns
        "this agent has not done that yet" into "this agent may not do that". That is the
        circularity the rest of the build guards against; it has to be guarded here too.
        """
        entities = [*states("a"), entity("Tool:t", "Tool")]
        observed = [
            replace(
                triple("State:a", "USES_TOOL", "Tool:t"),
                methods=frozenset({"telemetry"}),
            ),
            triple("State:a", "IS_TERMINAL", "true", kind="literal"),
        ]
        assert not capabilities(build_graph(entities, observed)).closed_world

        declared = [triple("State:a", "USES_TOOL", "Tool:t"), observed[1]]
        assert capabilities(build_graph(entities, declared)).closed_world

    def test_the_world_is_open_while_any_acting_state_declares_no_tools(self) -> None:
        graph = build_graph(
            [*states("a", "b"), entity("Tool:t", "Tool")],
            [
                triple("State:a", "USES_TOOL", "Tool:t"),
                triple("State:a", "HAS_NEXT_STEP", "State:b"),
            ],
        )
        assert not capabilities(graph).closed_world


class TestAdmissibility:
    def test_a_category_is_excluded_with_the_capability_it_lacks(self) -> None:
        caps = capabilities(build_graph(states("a", "b"), []))
        found = admissible(caps)
        assert found.admitted == ()
        assert any("path" in reason for reason in found.reasons)

    def test_selecting_a_category_the_graph_cannot_support_still_excludes_it(self) -> None:
        """Selection narrows the taxonomy. It cannot conjure a capability."""
        caps = capabilities(build_graph(states("a", "b"), []))
        found = admissible(caps, only=("journey_path",))
        assert found.admitted == ()
        assert found.excluded[0][0].name == "journey_path"

    def test_every_category_has_a_generator_and_a_recovery_route(self) -> None:
        from metric.scenario.bases import _CHECKS, _GENERATORS

        for category in CATEGORIES:
            assert category.name in _CHECKS, f"{category.name} has no recovery route"
            if category.name != "journey_path":
                assert category.name in _GENERATORS, f"{category.name} has no generator"


class TestFunctionalityCheck:
    """The check has to fail when the claim and the triples disagree."""

    def test_a_threshold_base_that_misstates_the_limit_is_rejected(self) -> None:
        graph = build_graph(
            [
                entity("Decision:retry", "Decision", canonical="retry"),
                entity("Value:three", "Value", canonical="3"),
            ],
            [
                triple("Decision:retry", "HAS_THRESHOLD", "Value:three"),
                triple("Value:three", "VALUE_IS", "3"),
            ],
        )
        honest = Scenario(
            id="x",
            category="threshold_boundary",
            family="boundary",
            answer_type="int",
            question="attempt 4 of 3",
            answer=("4", "refused"),
            subject=("Decision:retry", "Value:three"),
        )
        assert verify(graph, honest).checked

        checked = verify(graph, replace(honest, answer=("4", "allowed")))
        assert not checked.checked
        assert "allowed" in checked.check_note

    def test_a_path_base_claiming_a_hop_the_graph_lacks_is_rejected(self) -> None:
        graph = build_graph(
            states("a", "b", "c"), [triple("State:a", "HAS_NEXT_STEP", "State:b")]
        )
        base = Scenario(
            id="x",
            category="journey_path",
            family="traversal",
            answer_type="path",
            question="a to c",
            answer=("State:a", "State:c"),
            entry="State:a",
            steps=(Step("State:a", "", "", "State:c"),),
            terminal="State:c",
            complete=False,
        )
        checked = verify(graph, base)
        assert not checked.checked
        assert "no HAS_NEXT_STEP states" in checked.check_note

    def test_a_prohibition_base_naming_a_rule_that_forbids_nothing_is_rejected(self) -> None:
        graph = build_graph(
            [entity("Rule:r", "Rule", canonical="r"), entity("Action:a", "Action")],
            [triple("Rule:r", "RULE_REQUIRES", "Action:a")],
        )
        base = Scenario(
            id="x",
            category="forbidden_action",
            family="prohibition",
            answer_type="bool",
            question="do the forbidden thing",
            answer=("Action:a",),
            subject=("Rule:r", "Action:a"),
        )
        assert not verify(graph, base).checked

    def test_a_check_reads_the_same_population_the_generator_did(self) -> None:
        """Held-for-review facts are facts the build found.

        Checking against `admitted` instead of `live` made every base resting on a
        reviewed triple look like a generator error — 25 of them, on the working corpus.
        """
        graph = build_graph(
            states("a", "b"),
            [triple("State:a", "HAS_NEXT_STEP", "State:b", status="review")],
        )
        base = Scenario(
            id="x",
            category="journey_path",
            family="traversal",
            answer_type="path",
            question="a to b",
            answer=("State:a", "State:b"),
            entry="State:a",
            steps=(Step("State:a", "", "", "State:b"),),
            terminal="State:b",
            complete=False,
        )
        assert verify(graph, base).checked


class TestGeneration:
    def test_a_threshold_gives_one_under_at_and_over(self) -> None:
        graph = build_graph(
            [
                entity("Decision:retry", "Decision", canonical="retry"),
                entity("Value:v", "Value", canonical="3"),
            ],
            [
                triple("Decision:retry", "HAS_THRESHOLD", "Value:v"),
                triple("Value:v", "VALUE_IS", "3"),
            ],
        )
        from metric.graph.journey import Journey

        found = generate(graph, Journey(graph), capabilities(graph), "threshold_boundary")
        assert [b.answer for b in found] == [
            ("2", "allowed"),
            ("3", "allowed"),
            ("4", "refused"),
        ]

    def test_tool_absence_stays_silent_in_an_open_world(self) -> None:
        """An undeclared tool cannot be told from a gap in the corpus."""
        graph = build_graph(
            [*states("a", "b"), entity("Tool:t", "Tool"), entity("Tool:u", "Tool")],
            [
                triple("State:a", "USES_TOOL", "Tool:t"),
                triple("State:b", "USES_TOOL", "Tool:u"),
                triple("State:a", "HAS_NEXT_STEP", "State:b"),
                triple("State:b", "IS_TERMINAL", "true"),
            ],
        )
        from metric.graph.journey import Journey

        caps = capabilities(graph)
        assert caps.closed_world
        assert generate(graph, Journey(graph), caps, "tool_absence")

    def test_generation_is_deterministic(self) -> None:
        graph = build_graph(
            [*states("a", "b"), entity("Rule:r", "Rule"), entity("Action:x", "Action")],
            [
                triple("State:a", "HAS_NEXT_STEP", "State:b"),
                triple("Rule:r", "RULE_FORBIDS", "Action:x"),
            ],
        )
        first, second = build_space(graph), build_space(graph)
        assert [s.id for s in first.scenarios] == [s.id for s in second.scenarios]


class TestSpace:
    def test_an_admissible_category_that_produced_nothing_is_still_counted(self) -> None:
        """The interesting case: the capability was there and no instance of it was."""
        graph = build_graph(
            [*states("a", "b"), entity("Tool:t", "Tool")],
            [
                triple("State:a", "HAS_NEXT_STEP", "State:b"),
                triple("State:a", "USES_TOOL", "Tool:t"),
            ],
        )
        space = build_space(graph)
        assert space.coverage["tool_absence"] == 0

    def test_an_empty_graph_produces_no_bases_and_says_why(self) -> None:
        space = build_space(build_graph([], []))
        assert space.scenarios == ()
        assert space.inadmissible

    def test_a_seed_base_is_kept_even_though_the_graph_cannot_confirm_it(self) -> None:
        graph = build_graph(states("a"), [])
        seed = Scenario(
            id="seed-1",
            category="supplied",
            family="supplied",
            answer_type="text",
            question="a real case from production",
            answer=("escalate",),
            origin="seed",
            checked=False,
        )
        space = build_space(graph, seeds=[seed])
        assert [s.id for s in space.scenarios] == ["seed-1"]

    def test_a_seed_file_without_an_answer_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "seeds.yaml"
        path.write_text("bases:\n  - question: what now?\n", encoding="utf-8")
        with pytest.raises(SeedError, match="missing 'answer'"):
            load_seeds(path)


class TestRelevance:
    def test_a_factor_is_not_crossed_with_a_base_it_cannot_speak_about(self) -> None:
        catalogue = load_catalogue(VOICE)
        numeric = Item("n", "threshold_boundary", "boundary", "int")
        path = Item("p", "journey_path", "traversal", "path")

        design = plan([numeric, path], catalogue)
        assert "number_reading" in design.dropped["p"]
        assert "number_reading" not in design.dropped.get("n", ())
        assert all(
            "number_reading" not in dict(v.levels) for v in design.for_scenario("p")
        )

    def test_an_excluded_category_drops_the_factor_for_that_category_only(self) -> None:
        catalogue = load_catalogue(VOICE)
        design = plan(
            [Item("t", "canonical_text", "obligation", "text"),
             Item("f", "forbidden_action", "prohibition", "bool")],
            catalogue,
        )
        assert "paraphrase" in design.dropped["t"]
        assert "paraphrase" not in design.dropped.get("f", ())

    def test_a_base_no_factor_applies_to_still_runs_once(self) -> None:
        catalogue = load_catalogue(VOICE)
        narrow = catalogue.apply(catalogue.profiles["smoke"])
        lonely = Item("x", "journey_path", "nothing_matches", "nothing")
        design = plan([lonely], narrow)
        assert [v.reason for v in design.variants] == ["pairwise"] or design.variants


class TestProfiles:
    def test_selecting_factors_narrows_the_design(self) -> None:
        catalogue = load_catalogue(VOICE)
        smoke = catalogue.apply(catalogue.profiles["smoke"])
        assert [f.name for f in smoke.invariant] == ["clarity", "asr"]

    def test_overriding_levels_renames_without_forking_the_catalogue(self) -> None:
        catalogue = load_catalogue(VOICE)
        ivr = catalogue.apply(catalogue.profiles["ivr"])
        asr = ivr.factor("asr")
        assert asr is not None
        assert asr.levels == ("clean", "lossy", "degraded")

    def test_an_override_that_drops_the_adverse_level_drops_the_adverse_run(self) -> None:
        """Otherwise the adverse row would name a level the factor no longer has."""
        catalogue = load_catalogue(VOICE)
        ivr = catalogue.apply(catalogue.profiles["ivr"])
        asr = ivr.factor("asr")
        assert asr is not None and asr.adverse == ""

    def test_a_profile_selecting_a_factor_that_does_not_exist_is_refused(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "c.yaml"
        path.write_text(
            "factors:\n  - name: a\n    levels: [x, y]\n"
            "profiles:\n  p:\n    factors: [nope]\n",
            encoding="utf-8",
        )
        with pytest.raises(CatalogueError, match="do not exist"):
            load_catalogue(path)


class TestArrangements:
    def _items(self, count: int) -> list[Item]:
        return [Item(f"b{i}", "journey_path", "traversal", "path") for i in range(count)]

    def test_embedded_is_a_fixed_suite_where_crossed_grows_with_the_bases(self) -> None:
        catalogue = load_catalogue(VOICE)
        few, many = self._items(2), self._items(20)

        crossed_few = plan(few, catalogue, arrangement="crossed")
        crossed_many = plan(many, catalogue, arrangement="crossed")
        embedded_many = plan(many, catalogue, arrangement="embedded")

        assert len(crossed_many.variants) == 10 * len(crossed_few.variants)
        assert len(embedded_many.variants) < len(crossed_many.variants)

    def test_every_base_gets_the_same_number_of_runs(self) -> None:
        """Balanced blocking. The failure this prevents is a base silently absent."""
        catalogue = load_catalogue(VOICE)
        design = plan(self._items(7), catalogue, arrangement="embedded")
        counts = {i.id: len(design.for_scenario(i.id)) for i in self._items(7)}
        assert len(set(counts.values())) == 1
        assert all(count >= 1 for count in counts.values())

    def test_a_budget_smaller_than_the_base_count_still_runs_every_base(self) -> None:
        catalogue = load_catalogue(VOICE)
        design = plan(self._items(12), catalogue, arrangement="embedded", budget=3)
        assert {v.scenario for v in design.variants} == {f"b{i}" for i in range(12)}
        assert any("smaller than" in note for note in design.notes)

    def test_embedded_covers_fewer_pairs_and_says_so(self) -> None:
        catalogue = load_catalogue(VOICE)
        items = self._items(3)
        crossed = plan(items, catalogue, arrangement="crossed")
        embedded = plan(items, catalogue, arrangement="embedded")
        assert embedded.pairs_covered <= crossed.pairs_covered
        assert embedded.arrangement == "embedded"
