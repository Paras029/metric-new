from __future__ import annotations

from pathlib import Path

import pytest

from metric.contract.compile import build_contract, compile_assertions
from metric.ontology.schema import SchemaError, load_schema
from metric.resolve import resolve_for_scenario, resolve_for_trace
from metric.trace.binding import bind
from metric.trace.galileo import read_galileo_export

REPO = Path(__file__).resolve().parents[1]
CORE = REPO / "schemas" / "core.ontology.yaml"
DEMO = REPO / "fixtures" / "card_auth.trace.json"


class TestDeclaredChecks:
    def test_every_core_relation_says_how_it_is_checked_or_that_it_is_not(
        self, core_schema
    ) -> None:
        assert core_schema.undeclared(frozenset(core_schema.relations)) == ()

    def test_a_use_case_relation_declares_its_own_check(self, card_auth_schema) -> None:
        spec = card_auth_schema.relations["TRANSFERS_TO"]
        assert spec.checks is not None and spec.checks.kind == "action_required"

    def test_an_unknown_assertion_kind_is_refused_at_load(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "version: 1\nname: bad\nentity_types:\n  domain: [Widget]\n"
            "relations:\n  - name: DOES_SOMETHING\n    domain: [State]\n    range: [Widget]\n"
            "    checks:\n      kind: telepathy\n      dimension: policy\n      scope: journey\n",
            encoding="utf-8",
        )
        with pytest.raises(SchemaError, match="not a known assertion kind"):
            load_schema(CORE, bad)

    def test_a_relation_with_neither_declaration_is_reported(self, tmp_path: Path, built) -> None:
        silent = tmp_path / "silent.yaml"
        silent.write_text(
            "version: 1\nname: silent\nentity_types:\n  domain: [System]\n"
            "relations:\n  - name: TRANSFERS_TO\n    domain: [State]\n    range: [System]\n",
            encoding="utf-8",
        )
        schema = load_schema(CORE, silent)
        _, notes = compile_assertions(built.graph, schema)
        assert any("TRANSFERS_TO" in note and "not_checkable" in note for note in notes)


class TestCompilation:
    def test_prohibitions_and_limits_both_compile(self, built) -> None:
        assertions, _ = compile_assertions(built.graph, built.schema)
        kinds = {a.kind for a in assertions}
        assert {"action_forbidden", "count_limit", "terminal_expected"} <= kinds

    def test_a_threshold_carries_the_number_not_the_value_node(self, built) -> None:
        assertions, _ = compile_assertions(built.graph, built.schema)
        limits = [a for a in assertions if a.kind == "count_limit"]
        assert limits and all(a.expected[0].isdigit() for a in limits)

    def test_an_unreviewed_extraction_can_advise_but_not_block(self, built) -> None:
        assertions, _ = compile_assertions(built.graph, built.schema)
        provisional = [a for a in assertions if a.provisional]
        assert provisional
        assert all(a.severity == "advisory" and not a.blocking for a in provisional)

    def test_a_rule_that_states_its_own_severity_outranks_materiality(self, reviewable) -> None:
        reviewable.answer_many(
            [(q.id, "approve") for q in reviewable.result.questions
             if q.kind == "review/unwitnessed"]
        )
        assertions, _ = compile_assertions(reviewable.graph, reviewable.schema)
        blockers = [a for a in assertions if a.severity == "blocker"]
        assert blockers, "the grounded-outcome rule declares HAS_SEVERITY blocker"

    def test_every_assertion_carries_the_words_it_came_from(self, built) -> None:
        assertions, _ = compile_assertions(built.graph, built.schema)
        assert all(a.sources for a in assertions)
        assert all(a.evidence for a in assertions if "EMITTED" not in str(a.sources))

    def test_a_deterministic_reading_is_a_higher_rung_than_a_model_one(self, built) -> None:
        assertions, _ = compile_assertions(built.graph, built.schema)
        assert {a.level for a in assertions} <= {"L1", "L2", "L3"}


class TestResolution:
    def test_both_entry_points_produce_the_same_kind_of_contract(self, built) -> None:
        scenario = built.space.scenarios[0]
        bound = bind(
            read_galileo_export(DEMO), built.graph, checkpoint_variable=built.checkpoint_variable
        )
        from_scenario = resolve_for_scenario(
            built.graph, built.schema, scenario, identity=built.identity
        )
        from_trace = resolve_for_trace(built.graph, built.schema, bound, identity=built.identity)

        assert from_scenario.identity == from_trace.identity
        assert from_scenario.binding.startswith("scenario:")
        assert from_trace.binding.startswith("trace:")
        assert set(from_scenario.of_kind("action_forbidden")) & set(
            from_trace.of_kind("action_forbidden")
        ), "journey-scoped rules hold on every path and in every trace"

    def test_narrowing_never_drops_a_journey_wide_rule(self, built) -> None:
        everything = build_contract(
            built.graph, built.schema, identity=built.identity, binding="all"
        )
        narrow = build_contract(
            built.graph, built.schema, identity=built.identity, binding="none", scope=()
        )
        journey = [a for a in everything.assertions if a.scope == "journey"]
        assert journey
        assert set(journey) <= set(narrow.assertions)
