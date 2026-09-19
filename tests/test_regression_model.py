"""The adjusted model: separating an effect from the company it keeps.

The test that matters is the confound one. A marginal comparison cannot tell a level that
causes failures from a level that was merely paired with one, and a pairwise design
guarantees some of that pairing. If the adjusted model does not drop the passenger, it is
not earning its place.
"""

from __future__ import annotations

from metric.attribution import Outcome, attribute
from metric.regression import adjust


def runs(spec: list[tuple[dict[str, str], int, int]]) -> list[Outcome]:
    """`[(levels, passes, failures)]` expanded into individual runs."""
    out: list[Outcome] = []
    for index, (levels, passes, failures) in enumerate(spec):
        assignment = tuple(sorted(levels.items()))
        for n in range(passes + failures):
            out.append(
                Outcome(
                    variant=f"v{index}-{n}",
                    scenario=f"s{index}",
                    levels=assignment,
                    passed=n < passes,
                )
            )
    return out


class TestConfounding:
    def test_a_level_that_only_rode_along_is_dropped(self) -> None:
        """`cause` drives every failure; `passenger` is merely correlated with it.

        Marginal comparison reports both. The adjusted model, holding the other factor
        fixed, should report only the cause.
        """
        cohort = runs(
            [
                # cause=bad almost always arrives with passenger=b
                ({"cause": "bad", "passenger": "b"}, 0, 40),
                ({"cause": "bad", "passenger": "a"}, 0, 5),
                ({"cause": "good", "passenger": "a"}, 40, 0),
                ({"cause": "good", "passenger": "b"}, 5, 0),
            ]
        )

        marginal = {(e.factor, e.level) for e in attribute(cohort).significant}
        assert ("passenger", "b") in marginal, "the confound should be visible marginally"

        adjusted = {(c.factor, c.level) for c in adjust(cohort).significant}
        assert ("cause", "bad") in adjusted
        assert ("passenger", "b") not in adjusted

    def test_two_real_causes_are_both_kept(self) -> None:
        """Adjustment must not simply suppress everything but the strongest column."""
        cohort = runs(
            [
                ({"a": "bad", "b": "bad"}, 0, 30),
                ({"a": "bad", "b": "good"}, 8, 22),
                ({"a": "good", "b": "bad"}, 8, 22),
                ({"a": "good", "b": "good"}, 30, 0),
            ]
        )
        adjusted = {(c.factor, c.level) for c in adjust(cohort).significant}
        assert ("a", "bad") in adjusted
        assert ("b", "bad") in adjusted


class TestSeparation:
    def test_a_level_under_which_everything_failed_gives_a_finite_estimate(self) -> None:
        """Unpenalised, this coefficient runs to infinity and the fit never converges.

        It is also the case most worth reporting, so failing to fit it is not an option.
        """
        cohort = runs([({"asr": "heavy"}, 0, 40), ({"asr": "clean"}, 40, 0)])
        model = adjust(cohort)
        assert model.converged

        # Which of the two becomes the reference is a presentation choice — the counts
        # are tied, so it falls to the name — and the fit is the same either way with the
        # sign flipped. What has to hold is that the estimate is finite and decisive.
        (effect,) = model.coefficients
        assert effect.significant
        assert 0.0 < effect.odds_ratio < float("inf")
        assert not (effect.odds_interval.low < 1.0 < effect.odds_interval.high)
        worse = effect.level if effect.odds_ratio < 1.0 else effect.reference
        assert worse == "heavy"

    def test_the_penalty_is_reported(self) -> None:
        assert adjust(runs([({"a": "x"}, 5, 5), ({"a": "y"}, 5, 5)])).ridge > 0


class TestTheModel:
    def test_the_reference_is_the_best_observed_level(self) -> None:
        """A coefficient against an arbitrary reference is an unlabelled number."""
        cohort = runs([({"a": "rare"}, 3, 3), ({"a": "common"}, 30, 30)])
        model = adjust(cohort, min_cell=2)
        assert all(c.reference == "common" for c in model.coefficients)

    def test_a_factor_with_one_usable_level_is_left_out_and_named(self) -> None:
        cohort = runs([({"a": "x", "b": "only"}, 20, 20), ({"a": "y", "b": "only"}, 20, 20)])
        model = adjust(cohort)
        assert all(c.factor != "b" for c in model.coefficients)
        assert any("b has fewer than two levels" in note for note in model.notes)

    def test_nothing_is_significant_when_nothing_matters(self) -> None:
        cohort = runs(
            [
                ({"a": "x", "b": "p"}, 25, 25),
                ({"a": "y", "b": "q"}, 25, 25),
                ({"a": "x", "b": "q"}, 25, 25),
                ({"a": "y", "b": "p"}, 25, 25),
            ]
        )
        assert adjust(cohort).significant == ()

    def test_the_fit_quality_is_reported_and_bounded(self) -> None:
        strong = adjust(runs([({"a": "bad"}, 0, 40), ({"a": "good"}, 40, 0)]))
        weak = adjust(runs([({"a": "x"}, 20, 20), ({"a": "y"}, 20, 20)]))
        assert 0.0 <= weak.pseudo_r2 < strong.pseudo_r2 <= 1.0

    def test_an_empty_cohort_says_so(self) -> None:
        model = adjust([])
        assert model.coefficients == ()
        assert model.notes == ("no runs to model",)

    def test_the_same_cohort_always_gives_the_same_model(self) -> None:
        cohort = runs([({"a": "x"}, 30, 10), ({"a": "y"}, 10, 30)])
        assert adjust(cohort).as_dict() == adjust(cohort).as_dict()
