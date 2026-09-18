from __future__ import annotations

from metric.admit.gate import admit
from metric.admit.grounding import locate
from metric.extract.harvest import harvest_rules, harvest_values
from metric.ontology.types import Candidate, Passage

PASSAGE = Passage(
    id="pg1",
    doc_id="d1",
    location="§3.D",
    kind="prose",
    heading_path=("Operating procedure",),
    text=(
        "D. Failed authentication and retry. If authentication fails, inform the customer "
        "that the authentication was unsuccessful and ask them to try again. The bot may "
        "make up to 3 total authentication attempts. It must not make a fourth attempt."
    ),
)
PASSAGES = {PASSAGE.id: PASSAGE}


def candidate(**overrides: str) -> Candidate:
    base = {
        "head": "authenticate_customer",
        "head_type": "Tool",
        "relation": "RETURNS",
        "tail": "FAILED",
        "tail_type": "Outcome",
        "passage_id": PASSAGE.id,
        "quote": "The bot may make up to 3 total authentication attempts.",
        "method": "llm",
    }
    return Candidate(**{**base, **overrides})  # type: ignore[arg-type]


class TestGrounding:
    def test_an_exact_quote_is_located(self) -> None:
        found = locate("It must not make a fourth attempt.", PASSAGE.text)
        assert found is not None and found.exact
        assert PASSAGE.text[found.start : found.end] == "It must not make a fourth attempt."

    def test_collapsed_whitespace_and_typography_still_match(self) -> None:
        found = locate("The  bot may make\nup to 3 total", PASSAGE.text)
        assert found is not None and not found.exact
        assert found.text == "The bot may make up to 3 total"

    def test_the_span_records_the_source_wording_not_the_claim(self) -> None:
        found = locate("the bot MAY make up to 3 total", PASSAGE.text)
        assert found is not None
        assert found.text == "The bot may make up to 3 total"

    def test_a_reworded_quote_is_not_located(self) -> None:
        assert locate("The bot is allowed three attempts in total.", PASSAGE.text) is None

    def test_a_quote_too_short_to_be_evidence_is_refused(self) -> None:
        assert locate("the", PASSAGE.text) is None


class TestHarvest:
    def test_a_limit_is_captured_with_its_unit(self) -> None:
        values = harvest_values(PASSAGE)
        assert [(c.head, c.tail) for c in values] == [("3 total authentication attempts", "3")]
        assert values[0].method == "deterministic"

    def test_a_prohibition_becomes_a_rule_with_a_severity(self) -> None:
        rules = harvest_rules(PASSAGE)
        severities = {c.tail for c in rules if c.relation == "HAS_SEVERITY"}
        assert "error" in severities
        stated = [c.tail for c in rules if c.relation == "RULE_STATES"]
        assert any("must not make a fourth attempt" in text for text in stated)

    def test_every_harvested_candidate_quotes_its_own_passage(self) -> None:
        for found in harvest_values(PASSAGE) + harvest_rules(PASSAGE):
            assert locate(found.quote, PASSAGE.text) is not None


class TestGate:
    def test_a_grounded_candidate_becomes_a_triple(self, core_schema) -> None:
        result = admit([candidate()], schema=core_schema, passages=PASSAGES)
        assert len(result.triples) == 1
        assert result.triples[0].spans[0].passage_id == PASSAGE.id
        assert not result.rejections

    def test_a_fabricated_quote_is_quarantined(self, core_schema) -> None:
        result = admit(
            [candidate(quote="The bot may make up to 5 attempts.")],
            schema=core_schema,
            passages=PASSAGES,
        )
        assert not result.triples
        assert result.rejections[0].criterion == "quote"

    def test_a_malformed_relation_fails_before_the_quote_is_looked_for(self, core_schema) -> None:
        result = admit(
            [candidate(relation="RETURNS", head_type="Turn", quote="nonsense that is not here")],
            schema=core_schema,
            passages=PASSAGES,
        )
        assert result.rejections[0].criterion == "schema"

    def test_a_requirement_read_off_a_prohibition_is_caught(self, core_schema) -> None:
        result = admit(
            [
                candidate(
                    head="attempt limit rule",
                    head_type="Rule",
                    relation="RULE_REQUIRES",
                    tail="make a fourth attempt",
                    tail_type="Action",
                    quote="It must not make a fourth attempt.",
                )
            ],
            schema=core_schema,
            passages=PASSAGES,
        )
        assert result.rejections[0].criterion == "polarity"

    def test_a_prohibition_with_no_negation_in_its_quote_is_caught(self, core_schema) -> None:
        result = admit(
            [
                candidate(
                    head="attempt limit rule",
                    head_type="Rule",
                    relation="RULE_FORBIDS",
                    tail="make a fourth attempt",
                    tail_type="Action",
                    quote="The bot may make up to 3 total authentication attempts.",
                )
            ],
            schema=core_schema,
            passages=PASSAGES,
        )
        assert result.rejections[0].criterion == "polarity"

    def test_a_value_absent_from_the_cited_span_is_caught(self, core_schema) -> None:
        result = admit(
            [
                candidate(
                    head="5 attempts",
                    head_type="Value",
                    relation="VALUE_IS",
                    tail="5",
                    tail_type="literal",
                    quote="The bot may make up to 3 total authentication attempts.",
                )
            ],
            schema=core_schema,
            passages=PASSAGES,
        )
        assert result.rejections[0].criterion == "value"

    def test_a_spelled_out_number_supports_its_digit_form(self, core_schema) -> None:
        passage = Passage(
            id="pg2",
            doc_id="d1",
            location="§1",
            kind="prose",
            heading_path=(),
            text="The bot allows a maximum of three authentication attempts.",
        )
        result = admit(
            [
                candidate(
                    head="3 authentication attempts",
                    head_type="Value",
                    relation="VALUE_IS",
                    tail="3",
                    tail_type="literal",
                    passage_id=passage.id,
                    quote="a maximum of three authentication attempts",
                )
            ],
            schema=core_schema,
            passages={passage.id: passage},
        )
        assert not result.rejections
        assert result.triples[0].tail == "3"

    def test_a_different_number_is_still_rejected(self, core_schema) -> None:
        result = admit(
            [
                candidate(
                    head="4 attempts",
                    head_type="Value",
                    relation="VALUE_IS",
                    tail="4",
                    tail_type="literal",
                    quote="The bot may make up to 3 total authentication attempts.",
                )
            ],
            schema=core_schema,
            passages=PASSAGES,
        )
        assert result.rejections[0].criterion == "value"

    def test_surface_forms_are_collected_onto_one_entity(self, core_schema) -> None:
        result = admit(
            [candidate(), candidate(head="Authenticate Customer")],
            schema=core_schema,
            passages=PASSAGES,
        )
        tools = [e for e in result.entities if e.type == "Tool"]
        assert len(tools) == 1
        assert tools[0].surfaces == frozenset({"authenticate_customer", "Authenticate Customer"})
