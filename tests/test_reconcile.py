from __future__ import annotations

from metric.graph.model import build
from metric.ontology.types import Entity, Span, Triple
from metric.reconcile import conflicts
from metric.reconcile.dedup import apply_witness_bar, merge
from metric.reconcile.integrity import check
from metric.reconcile.run import reconcile


def span(passage: str, quote: str = "quoted text here") -> Span:
    return Span(passage_id=passage, start=0, end=len(quote), quote=quote)


def triple(
    head: str,
    relation: str,
    tail: str,
    *,
    passages: tuple[str, ...] = ("pg1",),
    methods: tuple[str, ...] = ("llm",),
    materiality: str = "normal",
    tail_kind: str = "entity",
) -> Triple:
    return Triple(
        head=head,
        relation=relation,
        tail=tail,
        tail_kind=tail_kind,  # type: ignore[arg-type]
        spans=tuple(span(p) for p in passages),
        methods=frozenset(methods),  # type: ignore[arg-type]
        materiality=materiality,  # type: ignore[arg-type]
    )


def entity(entity_id: str, entity_type: str, name: str) -> Entity:
    return Entity(id=entity_id, type=entity_type, canonical=name, surfaces=frozenset({name}))


class TestMerge:
    def test_one_fact_stated_twice_keeps_both_citations(self) -> None:
        merged = merge(
            [
                triple("Tool:a", "RETURNS", "Outcome:ok", passages=("pg1",)),
                triple("Tool:a", "RETURNS", "Outcome:ok", passages=("pg2",)),
            ]
        )
        assert len(merged) == 1
        assert {s.passage_id for s in merged[0].spans} == {"pg1", "pg2"}

    def test_the_same_span_arriving_twice_collapses(self) -> None:
        merged = merge([triple("Tool:a", "RETURNS", "Outcome:ok")] * 2)
        assert len(merged[0].spans) == 1

    def test_methods_and_materiality_are_unioned_upwards(self) -> None:
        merged = merge(
            [
                triple("Value:v", "VALUE_IS", "3", tail_kind="literal", methods=("llm",)),
                triple(
                    "Value:v",
                    "VALUE_IS",
                    "3",
                    tail_kind="literal",
                    methods=("deterministic",),
                    materiality="high",
                ),
            ]
        )
        assert merged[0].methods == {"llm", "deterministic"}
        assert merged[0].materiality == "high"


class TestWitnessBar:
    def test_a_lone_model_claim_that_matters_goes_to_review(self) -> None:
        barred = apply_witness_bar(
            [triple("State:a", "HAS_NEXT_STEP", "State:b", materiality="high")]
        )
        assert barred[0].status == "review"

    def test_a_second_passage_is_enough(self) -> None:
        barred = apply_witness_bar(
            [
                triple(
                    "State:a",
                    "HAS_NEXT_STEP",
                    "State:b",
                    materiality="high",
                    passages=("pg1", "pg2"),
                )
            ]
        )
        assert barred[0].status == "admitted"

    def test_a_deterministic_origin_is_enough(self) -> None:
        barred = apply_witness_bar(
            [
                triple(
                    "State:a",
                    "HAS_NEXT_STEP",
                    "State:b",
                    materiality="high",
                    methods=("deterministic",),
                )
            ]
        )
        assert barred[0].status == "admitted"

    def test_ordinary_triples_are_untouched(self) -> None:
        barred = apply_witness_bar([triple("Tool:a", "USES_TOOL", "Tool:b")])
        assert barred[0].status == "admitted"


class TestConflicts:
    def test_two_destinations_for_one_outcome_conflict(self, core_schema) -> None:
        triples = [
            triple("Outcome:failed", "LEADS_TO", "State:retry"),
            triple("Outcome:failed", "LEADS_TO", "State:transfer"),
        ]
        found = conflicts.detect(triples, schema=core_schema, label=lambda x: x)
        assert [c.kind for c in found] == ["cardinality"]

    def test_a_terminal_state_with_a_successor_conflicts(self, core_schema) -> None:
        triples = [
            triple("State:end", "IS_TERMINAL", "true", tail_kind="literal"),
            triple("State:end", "HAS_NEXT_STEP", "State:other"),
        ]
        found = conflicts.detect(triples, schema=core_schema, label=lambda x: x)
        assert [c.kind for c in found] == ["terminal"]

    def test_opposite_obligations_on_one_target_conflict(self, core_schema) -> None:
        triples = [
            triple("Rule:a", "RULE_REQUIRES", "Action:transfer"),
            triple("Rule:b", "RULE_FORBIDS", "Action:transfer"),
        ]
        found = conflicts.detect(triples, schema=core_schema, label=lambda x: x)
        assert [c.kind for c in found] == ["deontic"]

    def test_an_unresolved_conflict_marks_both_sides_and_raises_a_question(
        self, core_schema
    ) -> None:
        triples = [
            triple("Outcome:failed", "LEADS_TO", "State:retry"),
            triple("Outcome:failed", "LEADS_TO", "State:transfer"),
        ]
        found = conflicts.detect(triples, schema=core_schema, label=lambda x: x)
        resolved = conflicts.resolve(triples, found, effective_dates={})
        assert {t.status for t in resolved.triples} == {"conflicted"}
        assert len(resolved.questions) == 1

    def test_a_later_effective_date_supersedes_an_earlier_one(self, core_schema) -> None:
        triples = [
            triple("Outcome:failed", "LEADS_TO", "State:retry", passages=("old",)),
            triple("Outcome:failed", "LEADS_TO", "State:transfer", passages=("new",)),
        ]
        found = conflicts.detect(triples, schema=core_schema, label=lambda x: x)
        resolved = conflicts.resolve(
            triples, found, effective_dates={"old": "2025-01-01", "new": "2026-01-01"}
        )
        statuses = {t.tail: t.status for t in resolved.triples}
        assert statuses == {"State:retry": "superseded", "State:transfer": "admitted"}
        assert not resolved.questions

    def test_equal_dates_do_not_decide(self, core_schema) -> None:
        triples = [
            triple("Outcome:failed", "LEADS_TO", "State:retry", passages=("a",)),
            triple("Outcome:failed", "LEADS_TO", "State:transfer", passages=("b",)),
        ]
        found = conflicts.detect(triples, schema=core_schema, label=lambda x: x)
        resolved = conflicts.resolve(
            triples, found, effective_dates={"a": "2026-01-01", "b": "2026-01-01"}
        )
        assert {t.status for t in resolved.triples} == {"conflicted"}


class TestIntegrity:
    def test_an_outcome_with_no_destination_raises_a_question_and_nothing_else(self) -> None:
        graph = build(
            [entity("Tool:t", "Tool", "transfer_to_ccp"), entity("Outcome:f", "Outcome", "FAILED")],
            [
                triple(
                    "Tool:t",
                    "RETURNS",
                    "Outcome:f",
                    materiality="high",
                    methods=("deterministic",),
                )
            ],
        )
        questions = check(graph)
        assert [q.kind for q in questions] == ["integrity/outcome-destination"]
        assert not graph.by_relation("LEADS_TO")

    def test_one_name_returned_by_two_tools_is_reported(self) -> None:
        graph = build(
            [
                entity("Tool:a", "Tool", "authenticate_customer"),
                entity("Tool:b", "Tool", "transfer_to_ccp"),
                entity("Outcome:f", "Outcome", "FAILED"),
            ],
            [
                triple("Tool:a", "RETURNS", "Outcome:f", methods=("deterministic",)),
                triple("Tool:b", "RETURNS", "Outcome:f", methods=("deterministic",)),
            ],
        )
        kinds = [q.kind for q in check(graph)]
        assert "integrity/outcome-collision" in kinds

    def test_a_decision_with_one_branch_is_reported(self) -> None:
        graph = build(
            [entity("Decision:d", "Decision", "auth result"), entity("Outcome:o", "Outcome", "ok")],
            [triple("Decision:d", "HAS_OUTCOME", "Outcome:o", methods=("deterministic",))],
        )
        assert "integrity/decision-branches" in [q.kind for q in check(graph)]

    def test_a_condition_on_an_undeclared_variable_is_reported(self) -> None:
        graph = build(
            [entity("Condition:c", "Condition", "attempts exhausted"),
             entity("StateVariable:v", "StateVariable", "attempt count")],
            [triple("Condition:c", "ON_VARIABLE", "StateVariable:v", methods=("deterministic",))],
        )
        assert "integrity/undeclared-variable" in [q.kind for q in check(graph)]

    def test_a_clean_graph_raises_nothing(self) -> None:
        graph = build(
            [entity("Tool:t", "Tool", "authenticate_customer")],
            [
                triple(
                    "Tool:t",
                    "IS_STATE_CHANGING",
                    "false",
                    tail_kind="literal",
                    methods=("deterministic",),
                )
            ],
        )
        assert check(graph) == []


class TestReconcileOrder:
    def test_restatements_merge_before_they_can_look_like_contradictions(self, core_schema) -> None:
        triples = [
            triple("Outcome:ok", "LEADS_TO", "State:transfer", passages=("pg1",)),
            triple("Outcome:ok", "LEADS_TO", "State:transfer", passages=("pg2",)),
        ]
        result = reconcile(
            [entity("Outcome:ok", "Outcome", "AUTHENTICATED"),
             entity("State:transfer", "State", "transfer to CCP")],
            triples,
            schema=core_schema,
            effective_dates={},
        )
        assert result.conflicts == ()
        assert len(result.graph.triples) == 1
        assert len(result.graph.triples[0].spans) == 2

    def test_a_contradicted_triple_is_marked_contradicted_not_merely_unwitnessed(
        self, core_schema
    ) -> None:
        triples = [
            triple("Outcome:ok", "LEADS_TO", "State:a", materiality="high"),
            triple("Outcome:ok", "LEADS_TO", "State:b", materiality="high"),
        ]
        result = reconcile([], triples, schema=core_schema, effective_dates={})
        assert {t.status for t in result.graph.triples} == {"conflicted"}
