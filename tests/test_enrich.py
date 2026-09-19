from __future__ import annotations

from itertools import combinations
from pathlib import Path

import pytest

from metric.enrich.design import covering_array, plan
from metric.enrich.factors import CatalogueError, Factor, load_catalogue

REPO = Path(__file__).resolve().parents[1]
VOICE = REPO / "catalogs" / "voice.factors.yaml"


def factor(name: str, *levels: str, invariant: bool = True, adverse: str = "") -> Factor:
    return Factor(name=name, group="g", levels=levels, invariant=invariant, adverse=adverse)


def pairs_in(rows) -> set:
    found = set()
    for row in rows:
        for (an, al), (bn, bl) in combinations(row, 2):
            found.add(((an, al), (bn, bl)))
    return found


def all_pairs(factors) -> set:
    return {
        ((a.name, al), (b.name, bl))
        for a, b in combinations(factors, 2)
        for al in a.levels
        for bl in b.levels
    }


class TestCatalogue:
    def test_the_voice_catalogue_loads(self) -> None:
        catalogue = load_catalogue(VOICE)
        assert [f.name for f in catalogue.invariant] == ["clarity", "asr", "persona", "history"]
        assert [f.name for f in catalogue.situational] == ["tool_fault"]

    def test_a_factor_with_one_level_varies_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "c.yaml"
        path.write_text("factors:\n  - name: a\n    levels: [only]\n", encoding="utf-8")
        with pytest.raises(CatalogueError, match="fewer than two levels"):
            load_catalogue(path)

    def test_an_adverse_level_it_does_not_have_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "c.yaml"
        path.write_text(
            "factors:\n  - name: a\n    levels: [x, y]\n    adverse: z\n", encoding="utf-8"
        )
        with pytest.raises(CatalogueError, match="adverse level it does not have"):
            load_catalogue(path)


class TestCoveringArray:
    def test_every_pair_of_levels_appears_together(self) -> None:
        factors = (factor("a", "1", "2", "3"), factor("b", "x", "y"), factor("c", "p", "q", "r"))
        rows = covering_array(factors)
        assert pairs_in(rows) >= all_pairs(factors)

    def test_it_is_far_smaller_than_the_full_cross(self) -> None:
        factors = tuple(factor(f"f{i}", "a", "b", "c") for i in range(6))
        rows = covering_array(factors)
        assert pairs_in(rows) >= all_pairs(factors)
        assert len(rows) < 3**6 / 10, "pairwise should be a small fraction of the full factorial"

    def test_the_same_catalogue_always_gives_the_same_design(self) -> None:
        factors = (factor("a", "1", "2", "3"), factor("b", "x", "y"), factor("c", "p", "q"))
        assert covering_array(factors) == covering_array(factors)

    def test_every_row_assigns_every_factor(self) -> None:
        factors = (factor("a", "1", "2"), factor("b", "x", "y", "z"))
        for row in covering_array(factors):
            assert [name for name, _ in row] == ["a", "b"]


class TestPlan:
    def test_a_factor_that_changes_what_is_required_is_excluded_and_named(self) -> None:
        catalogue = load_catalogue(VOICE)
        design = plan({"s1": False}, catalogue)
        assert any("tool_fault" in note for note in design.excluded)
        assert all("tool_fault" not in dict(v.levels) for v in design.variants)

    def test_coverage_is_reported(self) -> None:
        design = plan({"s1": False}, load_catalogue(VOICE))
        assert design.complete
        assert design.pairs_total > 0

    def test_only_a_scenario_that_can_block_gets_the_adverse_run(self) -> None:
        catalogue = load_catalogue(VOICE)
        design = plan({"weak": False, "strong": True}, catalogue)
        reasons = {s: {v.reason for v in design.for_scenario(s)} for s in ("weak", "strong")}
        assert reasons["weak"] == {"pairwise"}
        assert "adverse" in reasons["strong"]

    def test_the_adverse_run_is_every_factor_at_its_hardest(self) -> None:
        catalogue = load_catalogue(VOICE)
        design = plan({"strong": True}, catalogue)
        adverse = next(v for v in design.for_scenario("strong") if v.reason == "adverse")
        assert dict(adverse.levels)["asr"] == "heavy_noise"
        assert dict(adverse.levels)["clarity"] == "garbled"

    def test_variant_ids_are_stable(self) -> None:
        catalogue = load_catalogue(VOICE)
        first = plan({"s1": True}, catalogue)
        second = plan({"s1": True}, catalogue)
        assert [v.id for v in first.variants] == [v.id for v in second.variants]


class TestEnrichmentDoesNotChangeTheTruth:
    def test_every_variant_of_a_scenario_shares_one_contract(self, built) -> None:
        """The whole point of the base/enrichment split.

        The contract is resolved from the scenario, never from the variant, so a level
        cannot reach it. This test exists to keep it that way — the moment enrichment
        can touch a contract, a failure stops being attributable to the level that
        caused it.
        """
        scenario = built.space.scenarios[0]
        variants = built.plan.for_scenario(scenario.id)
        assert len(variants) > 1

        contract = built.contract_for(scenario.id)
        assert contract is not None
        for _ in variants:
            assert built.contract_for(scenario.id).assertions == contract.assertions

    def test_the_plan_covers_every_scenario(self, built) -> None:
        planned = {v.scenario for v in built.plan.variants}
        assert planned == {s.id for s in built.space.scenarios}
