from __future__ import annotations

from pathlib import Path

import pytest

from metric.ontology.canonical import canonical_surface
from metric.ontology.ids import canonical_name, entity_id
from metric.ontology.schema import SchemaError, load_schema
from metric.ontology.types import Candidate

REPO = Path(__file__).resolve().parents[1]
CORE = REPO / "schemas" / "core.ontology.yaml"


def candidate(**overrides: str) -> Candidate:
    base = {
        "head": "authenticate_customer",
        "head_type": "Tool",
        "relation": "RETURNS",
        "tail": "AUTHENTICATED",
        "tail_type": "Outcome",
        "passage_id": "p1",
        "quote": "authenticate_customer returns AUTHENTICATED",
        "method": "llm",
    }
    return Candidate(**{**base, **overrides})  # type: ignore[arg-type]


class TestIdentity:
    def test_folding_ignores_case_punctuation_and_spacing(self) -> None:
        assert canonical_name("Authenticate Customer") == canonical_name("authenticate_customer")
        assert canonical_name("transfer to CCP!") == "transfer_to_ccp"

    def test_type_participates_so_names_cannot_merge_across_types(self) -> None:
        assert entity_id("Tool", "transfer") != entity_id("Action", "transfer")

    def test_empty_canonical_name_is_rejected_rather_than_hashed(self) -> None:
        with pytest.raises(ValueError):
            entity_id("Tool", "***")


class TestValueCanonicalForm:
    def test_phrasings_of_one_limit_collapse(self) -> None:
        forms = ["3 authentication attempts", "3 total authentication attempts", "3 attempts"]
        assert len({canonical_surface("Value", form) for form in forms}) == 1

    def test_same_number_different_unit_stays_distinct(self) -> None:
        assert canonical_surface("Value", "3 attempts") != canonical_surface("Value", "3 days")

    def test_non_quantities_fall_back_to_plain_folding(self) -> None:
        assert canonical_surface("Value", "AUTHENTICATED") == "authenticated"


class TestSchema:
    def test_core_loads(self, core_schema) -> None:
        assert "HAS_NEXT_STEP" in core_schema.relations
        assert core_schema.domain_types == frozenset()

    def test_extension_adds_domain_types_and_relations(self, card_auth_schema) -> None:
        assert "System" in card_auth_schema.domain_types
        assert "TRANSFERS_TO" in card_auth_schema.relations

    def test_extension_may_narrow_a_core_relation(self, core_schema, card_auth_schema) -> None:
        assert "Decision" in core_schema.relations["USES_TOOL"].domain
        assert "Decision" not in card_auth_schema.relations["USES_TOOL"].domain

    def test_extension_may_not_widen_a_core_relation(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "version: 1\nname: bad\nentity_types:\n  domain: [Widget]\n"
            "relations:\n  - name: LEADS_TO\n    domain: [Outcome, Widget]\n    range: [State]\n",
            encoding="utf-8",
        )
        with pytest.raises(SchemaError, match="widens the core domain"):
            load_schema(CORE, bad)


class TestSchemaCheck:
    def test_valid_candidate_passes(self, core_schema) -> None:
        assert core_schema.check(candidate()) is None

    def test_unknown_relation_is_named(self, core_schema) -> None:
        assert "unknown relation" in (core_schema.check(candidate(relation="INVENTED")) or "")

    def test_head_outside_the_domain_is_rejected(self, core_schema) -> None:
        problem = core_schema.check(candidate(head_type="Turn"))
        assert problem is not None and "does not accept a Turn head" in problem

    def test_enum_literal_is_checked_against_its_values(self, core_schema) -> None:
        problem = core_schema.check(
            candidate(
                head_type="Rule",
                relation="HAS_SEVERITY",
                tail="catastrophic",
                tail_type="literal",
            )
        )
        assert problem is not None and "not a permitted value" in problem

    def test_entity_tail_offered_as_a_literal_is_rejected(self, core_schema) -> None:
        problem = core_schema.check(candidate(tail_type="literal"))
        assert problem is not None and "takes an entity tail" in problem
