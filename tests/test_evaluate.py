from __future__ import annotations

from collections import Counter
from pathlib import Path

from metric.evaluate.run import evaluate_trace
from metric.trace.galileo import read_galileo_export

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "fixtures" / "card_auth.trace.json"
PRODUCTION = REPO / "grounding" / "03-otel-trace-sample-galileo.json"


def graded(space, path: Path):
    return evaluate_trace(
        space.graph,
        space.schema,
        read_galileo_export(path),
        identity=space.identity,
        checkpoint_variable=space.checkpoint_variable,
    )


class TestGrading:
    def test_the_planted_violation_is_caught(self, built) -> None:
        failures = graded(built, DEMO).failures
        assert [v.assertion.kind for v in failures] == ["count_limit"]
        assert "reached 4, over the limit of 3" in failures[0].detail

    def test_a_run_that_followed_the_journey_passes_the_journey_checks(self, built) -> None:
        verdicts = {
            (v.assertion.kind, v.outcome) for v in graded(built, DEMO).verdicts
        }
        assert ("terminal_expected", "pass") in verdicts
        assert ("transition_expected", "pass") in verdicts
        assert ("outcome_allowed", "pass") in verdicts

    def test_a_check_whose_situation_never_arose_is_not_a_pass(self, built) -> None:
        outcomes = Counter(v.outcome for v in graded(built, DEMO).verdicts)
        assert outcomes["not_applicable"] > 0

    def test_something_the_trace_cannot_show_is_undecided_not_passed(self, built) -> None:
        undecided = [v for v in graded(built, DEMO).verdicts if v.outcome == "undecided"]
        assert undecided
        assert all("no tool" in v.detail or "no state" in v.detail for v in undecided)

    def test_verdicts_carry_the_policy_they_came_from(self, built) -> None:
        for verdict in graded(built, DEMO).verdicts:
            assert verdict.assertion.sources
            assert verdict.detail


class TestAnotherAgentsTrace:
    def test_nothing_is_fabricated_when_the_ontology_does_not_fit(self, built) -> None:
        evaluation = graded(built, PRODUCTION)
        assert evaluation.binding_coverage == 0.0
        assert not evaluation.by_outcome("pass")
        assert not evaluation.by_outcome("fail")

    def test_what_the_agent_did_that_we_cannot_grade_is_listed(self, built) -> None:
        assert "check_fullssn_or_cm15" in graded(built, PRODUCTION).unbound


class TestReviewClosesTheLoop:
    def test_an_unreviewed_graph_can_advise_but_never_block(self, reviewable) -> None:
        evaluation = graded(reviewable, DEMO)
        assert evaluation.failures
        assert not evaluation.blocked, "nothing may block until a person has confirmed it"

    def test_approving_the_evidence_lets_the_same_failure_block(self, reviewable) -> None:
        reviewable.answer_many(
            [
                (q.id, "approve")
                for q in reviewable.result.questions
                if q.kind == "review/unwitnessed"
            ]
        )
        evaluation = graded(reviewable, DEMO)
        assert evaluation.blocked
        assert evaluation.failures[0].assertion.severity == "error"

    def test_a_decision_survives_the_question_it_answered_disappearing(self, reviewable) -> None:
        reviews = [
            q.id for q in reviewable.result.questions if q.kind == "review/unwitnessed"
        ]
        reviewable.answer_many([(q, "approve") for q in reviews])
        assert not [
            q for q in reviewable.result.questions if q.kind == "review/unwitnessed"
        ]

        reviewable.build()
        assert not [
            t for t in reviewable.graph.triples if t.status == "review"
        ], "an approval that undoes itself on the next build is worse than no approval"

    def test_rejecting_removes_a_triple_from_the_graph(self, reviewable) -> None:
        question = next(
            q for q in reviewable.result.questions if q.kind == "review/unwitnessed"
        )
        reviewable.answer(question.id, "reject")
        assert any(t.status == "rejected" for t in reviewable.graph.triples)
