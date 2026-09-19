"""Attribution: the statistics, and the claims they are not allowed to make."""

from __future__ import annotations

from metric.attribution import Outcome, attribute, weak_link, wilson


def cohort(spec: dict[tuple[str, ...], tuple[int, int]]) -> list[Outcome]:
    """`{(factor=level, ...): (passes, failures)}` expanded into runs."""
    runs: list[Outcome] = []
    for index, (levels, (passes, failures)) in enumerate(spec.items()):
        assignment = tuple(tuple(pair.split("=")) for pair in levels)  # type: ignore[misc]
        for n in range(passes + failures):
            runs.append(
                Outcome(
                    variant=f"v{index}-{n}",
                    scenario=f"s{index}",
                    levels=assignment,  # type: ignore[arg-type]
                    passed=n < passes,
                )
            )
    return runs


class TestWilson:
    def test_five_of_five_is_not_certainty(self) -> None:
        """The normal approximation says [1.0, 1.0] here, which five runs do not support."""
        interval = wilson(5, 5)
        assert interval.high == 1.0
        assert 0.5 < interval.low < 0.7

    def test_the_interval_narrows_as_the_cohort_grows(self) -> None:
        small = wilson(40, 50)
        large = wilson(400, 500)
        assert (large.high - large.low) < (small.high - small.low)

    def test_no_runs_is_not_a_rate_of_zero_with_confidence(self) -> None:
        assert wilson(0, 0) == wilson(0, 0)
        assert wilson(0, 0).low == 0.0


class TestAttribution:
    def test_a_level_that_halves_the_odds_is_found(self) -> None:
        runs = cohort(
            {("asr=clean",): (90, 10), ("asr=heavy_noise",): (40, 60)},
        )
        found = attribute(runs)
        noisy = next(e for e in found.effects if e.level == "heavy_noise")
        assert noisy.significant
        assert noisy.direction == "harms"
        assert noisy.odds_ratio < 1.0

    def test_a_level_that_does_nothing_is_not_reported_as_an_effect(self) -> None:
        runs = cohort({("persona=calm",): (50, 50), ("persona=impatient",): (50, 50)})
        assert attribute(runs).significant == ()

    def test_a_small_difference_in_a_small_cohort_is_not_significant(self) -> None:
        """The failure this prevents: six of ten against seven of ten, reported as a finding."""
        runs = cohort({("clarity=clear",): (7, 3), ("clarity=garbled",): (6, 4)})
        assert attribute(runs).significant == ()

    def test_correction_is_across_the_family_not_each_test_alone(self) -> None:
        """Twenty null comparisons at a nominal 5% would produce one finding uncorrected."""
        spec: dict[tuple[str, ...], tuple[int, int]] = {}
        for i in range(10):
            spec[(f"f{i}=a",)] = (30, 30)
            spec[(f"f{i}=b",)] = (30, 30)
        assert attribute(cohort(spec)).significant == ()

    def test_a_cell_too_small_to_compare_is_named_not_silently_dropped(self) -> None:
        runs = cohort({("asr=clean",): (50, 10), ("asr=rare",): (1, 1)})
        found = attribute(runs)
        assert any("not enough to compare" in note for note in found.notes)
        assert all(e.level != "rare" for e in found.effects)

    def test_a_factor_held_at_one_level_attributes_nothing(self) -> None:
        runs = cohort({("asr=clean",): (30, 30)})
        assert any("one level" in note for note in attribute(runs).notes)

    def test_every_run_failing_at_a_level_still_gives_a_finite_interval(self) -> None:
        """A zero cell is the case most worth reporting; it must not divide by zero."""
        runs = cohort({("asr=clean",): (60, 0), ("asr=heavy_noise",): (0, 60)})
        noisy = next(e for e in attribute(runs).effects if e.level == "heavy_noise")
        assert noisy.odds_ratio > 0
        assert noisy.odds_interval.high < float("inf")
        assert noisy.significant

    def test_an_empty_cohort_says_so_rather_than_reporting_zero_percent(self) -> None:
        found = attribute([])
        assert found.overall.total == 0
        assert found.notes == ("no runs to attribute",)

    def test_the_same_cohort_always_gives_the_same_answer(self) -> None:
        runs = cohort({("asr=clean",): (90, 10), ("asr=noisy",): (40, 60)})
        assert attribute(runs).as_dict() == attribute(runs).as_dict()


class _Observed:
    def __init__(self, tools: tuple[str, ...]) -> None:
        self.tools = tools


class _Turn:
    def __init__(self, turn: int, findings: tuple[str, ...], tools: tuple[str, ...]) -> None:
        self.turn = turn
        self.findings = findings
        self.observed = _Observed(tools)
        self.expected = _Observed(())


class TestWeakLink:
    def test_blame_lands_on_the_first_thing_that_went_wrong(self) -> None:
        turns = [
            _Turn(0, (), ("lookup",)),
            _Turn(1, ("called a tool this state does not declare",), ("verify",)),
            _Turn(2, ("moved somewhere that does not follow",), ("transfer",)),
        ]
        link = weak_link(turns)
        assert link is not None
        assert link.turn == 1
        assert link.component == "verify"
        assert len(link.downstream) == 1

    def test_a_clean_run_has_no_weak_link(self) -> None:
        assert weak_link([_Turn(0, (), ("lookup",))]) is None
