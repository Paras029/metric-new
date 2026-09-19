"""Running a planned variant, and grading it the way a production trace is graded.

The reference agent is the instrument here. A clean one must pass — if it does not, the
harness is wrong rather than the agent — and each injected flaw must produce the finding
that names it, and not a different one. Three of these tests are regressions for bugs the
clean baseline caught, which is the whole argument for having one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from metric.enrich.design import Item, plan
from metric.enrich.factors import load_catalogue
from metric.run.agents import FLAWS, GraphAgent
from metric.run.customer import ScriptedCustomer, dump_script
from metric.run.model import Reply
from metric.run.simulate import Settings, simulate, simulate_plan

REPO = Path(__file__).resolve().parents[1]
VOICE = REPO / "catalogs" / "voice.factors.yaml"


@pytest.fixture
def journey(built):
    """A traversal base and one variant of it — what the reference agent can actually do."""
    base = next(b for b in built.space.scenarios if b.category == "journey_path")
    return base, built.plan.for_scenario(base.id)[0]


def run_with(built, journey, *flaws: str, materialiser: str = "identity"):
    base, variant = journey
    return simulate(
        base,
        variant,
        GraphAgent(built.graph, flaws=flaws),
        graph=built.graph,
        schema=built.schema,
        identity_digest=built.identity,
        compiled=built.compiled,
        settings=Settings(
            checkpoint_variable=built.checkpoint_variable or "checkpoint",
            materialiser=materialiser,
        ),
    )


class TestTheBaseline:
    def test_a_clean_reference_agent_passes(self, built, journey) -> None:
        """If this fails, the harness is wrong, not the agent. That is what it is for."""
        run = run_with(built, journey)
        assert run.passed, (
            f"failures {[v.detail for v in run.evaluation.failures]} "
            f"findings {run.findings}"
        )
        assert run.gradable and run.staged

    def test_the_same_run_twice_is_the_same_run(self, built, journey) -> None:
        first, second = run_with(built, journey), run_with(built, journey)
        assert first.trace.as_dict() == second.trace.as_dict()
        assert first.passed == second.passed


class TestEachFlawIsCaught:
    @pytest.mark.parametrize(
        "flaw",
        [f for f in FLAWS if f != "no_checkpoint"],
    )
    def test_an_injected_defect_fails_the_run(self, built, journey, flaw: str) -> None:
        assert not run_with(built, journey, flaw).passed

    def test_a_jump_is_named_as_a_transition_the_graph_does_not_allow(
        self, built, journey
    ) -> None:
        run = run_with(built, journey, "jump")
        assert "transition_allowed" in {v.assertion.kind for v in run.evaluation.failures}
        assert any("does not follow it" in f for f in run.findings)

    def test_skipping_fixed_wording_is_named_as_such(self, built, journey) -> None:
        run = run_with(built, journey, "skip_wording")
        assert any("required wording" in f for f in run.findings)

    def test_a_tool_the_state_does_not_declare_fails_the_run(self, built, journey) -> None:
        """Caught by the turn walk rather than an assertion, and it has to count.

        Counting only compiled assertions let an agent calling tools it had no business
        calling pass, with the finding printed underneath it.
        """
        run = run_with(built, journey, "extra_tool")
        assert not run.passed
        assert any("does not declare" in f for f in run.findings)

    def test_an_agent_that_never_says_where_it_is_cannot_be_failed(
        self, built, journey
    ) -> None:
        """And must not therefore be counted as passing."""
        run = run_with(built, journey, "no_checkpoint")
        assert not run.gradable
        assert not run.usable


class TestRegressions:
    def test_the_agent_speaks_wire_names_not_entity_ids(self, built, journey) -> None:
        """Emitting ids made the binder resolve nothing while the trace looked plausible.

        Every tool then read as uncalled, and a clean agent failed for not calling a tool
        it had just called. A tool name in a trace is what the agent emits, and the
        telemetry profile is what maps it.
        """
        run = run_with(built, journey)
        called = {o.name for o in run.trace if o.kind == "tool_call"}
        assert called, "the walk called no tools at all"
        assert not any(name.startswith(("Tool:", "Outcome:")) for name in called), called
        assert run.evaluation.binding_coverage > 0.4

    def test_a_turn_reports_the_state_it_acted_in_not_the_one_it_moved_to(
        self, built, journey
    ) -> None:
        """Otherwise every turn carries one state's tools under the next state's name."""
        run = run_with(built, journey)
        for truth in run.evaluation.turns:
            if not truth.binding.certain or not truth.observed.tools:
                continue
            assert set(truth.observed.tools) <= set(truth.expected.tools), (
                f"turn {truth.turn} called {truth.observed.tools} at {truth.binding.states}"
            )

    def test_the_call_does_not_end_when_the_customer_stops_speaking(
        self, built, journey
    ) -> None:
        """An agent moves at the end of its turn.

        So the state it moves into — very often the one that has to transfer, or say the
        closing wording — never gets a turn of its own if the conversation stops the
        moment the script does.
        """
        base, _ = journey
        scripted = len(dump_script(base).splitlines())
        run = run_with(built, journey)
        assert len(run.trace.turns) > scripted
        assert run.trace.turns[-1].observations


class TestStaging:
    def test_a_run_that_never_reached_the_situation_is_not_attributed(
        self, built, journey
    ) -> None:
        """A conversation can bind perfectly and never touch the thing under test."""
        base, variant = journey
        elsewhere = next(
            b
            for b in built.space.scenarios
            if b.subject and not (set(b.subject) & set(base.entities))
        )
        run = simulate(
            elsewhere,
            variant,
            GraphAgent(built.graph),
            graph=built.graph,
            schema=built.schema,
            identity_digest=built.identity,
            compiled=built.compiled,
            settings=Settings(checkpoint_variable=built.checkpoint_variable or "checkpoint"),
        )
        assert run.usable == (run.gradable and run.staged)


class TestTheCohort:
    def test_only_usable_runs_reach_attribution(self, built) -> None:
        cohort = simulate_plan(
            built.space.scenarios,
            built.plan,
            GraphAgent(built.graph, flaws=("no_checkpoint",)),
            graph=built.graph,
            schema=built.schema,
            identity_digest=built.identity,
            compiled=built.compiled,
            settings=Settings(checkpoint_variable=built.checkpoint_variable or "checkpoint"),
            limit=12,
        )
        assert cohort.runs
        assert cohort.outcomes() == ()
        assert any("placed itself" in note for note in cohort.notes)

    def test_a_sample_of_the_plan_says_it_is_one(self, built) -> None:
        cohort = simulate_plan(
            built.space.scenarios,
            built.plan,
            GraphAgent(built.graph),
            graph=built.graph,
            schema=built.schema,
            identity_digest=built.identity,
            compiled=built.compiled,
            settings=Settings(checkpoint_variable=built.checkpoint_variable or "checkpoint"),
            limit=6,
        )
        assert len(cohort.runs) == 6
        assert any("sample of the plan" in note for note in cohort.notes)


class TestTheCustomer:
    def test_a_threshold_base_drives_as_many_attempts_as_it_names(self, built) -> None:
        base = next(
            b for b in built.space.scenarios if b.category == "threshold_boundary"
        )
        # The opening states the situation; the follow-ups are what drive it, so count
        # those. The base's answer names attempt N, and N-1 follow-ups get there.
        follow_ups = dump_script(base).splitlines()[1:]
        assert len(follow_ups) == max(0, int(base.answer[0]) - 1)

    def test_the_customer_stops_when_the_agent_finishes(self, built) -> None:
        base = built.space.scenarios[0]
        customer = ScriptedCustomer(base)
        assert customer.reply(Reply(finished=True)) is None


class TestMaterialising:
    def test_the_default_renderer_reports_every_level_as_unrendered(
        self, built, journey
    ) -> None:
        """A run under it varied nothing, and the report has to say so."""
        run = run_with(built, journey, materialiser="identity")
        assert set(run.unrendered) == {name for name, _ in run.levels}

    def test_the_voice_renderer_reaches_the_conversation(self, built, journey) -> None:
        from metric import enrich  # noqa: F401  - registers "voice"

        _, variant = journey
        levels = dict(variant.levels)
        plain = run_with(built, journey, materialiser="identity")
        voiced = run_with(built, journey, materialiser="voice")

        assert "clarity" not in voiced.unrendered
        if levels.get("asr") not in (None, "clean") or levels.get("clarity") != "clear":
            first_plain = plain.trace.turns[0].observations[0].value
            first_voiced = voiced.trace.turns[0].observations[0].value
            assert first_plain != first_voiced


class TestFactorConditionalFlaws:
    def test_a_defect_can_be_tied_to_one_level(self, built) -> None:
        catalogue = load_catalogue(VOICE)
        design = plan([Item("b", "journey_path", "traversal", "path")], catalogue)
        noisy = next(v for v in design.variants if dict(v.levels).get("asr") == "heavy_noise")
        clean = next(v for v in design.variants if dict(v.levels).get("asr") == "clean")

        flawed = {"heavy_noise": "skip_wording"}
        assert GraphAgent(built.graph, flaws=flawed, levels=dict(noisy.levels)).flaws
        assert not GraphAgent(built.graph, flaws=flawed, levels=dict(clean.levels)).flaws
