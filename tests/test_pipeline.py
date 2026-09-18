from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conftest import ScriptedGateway
from metric import reports, review
from metric.corpus.passages import read_passages
from metric.extract.batching import batch_passages
from metric.extract.glossary import Glossary
from metric.extract.triples import extract_batch
from metric.ontology.canonical import canonical_surface
from metric.ontology.ids import entity_id
from metric.pipeline import DocumentSpec, ingest

SCRIPT = [
    {
        "head": "authenticate_customer",
        "head_type": "Tool",
        "relation": "RETURNS",
        "tail": "AUTHENTICATED",
        "tail_type": "Outcome",
        "quote": "If authenticate_customer returns AUTHENTICATED",
    },
    {
        "head": "transfer_to_ccp",
        "head_type": "Tool",
        "relation": "RETURNS",
        "tail": "FAILED",
        "tail_type": "Outcome",
        "quote": "Example output: TRANSFERRED / FAILED",
    },
    {
        "head": "AUTHENTICATED",
        "head_type": "Outcome",
        "relation": "LEADS_TO",
        "tail": "transfer the call to CCP",
        "tail_type": "State",
        "quote": "Then transfer the call to CCP for further servicing.",
    },
]

ENTITIES = [
    {"surface": "authenticate_customer", "type": "Tool"},
    {"surface": "transfer_to_ccp", "type": "Tool"},
    {"surface": "AUTHENTICATED", "type": "Outcome"},
    {"surface": "FAILED", "type": "Outcome"},
]


def build(policy_path: Path, schema: Any) -> Any:
    gateway = ScriptedGateway(entities=ENTITIES, triples=list(SCRIPT))
    return ingest([DocumentSpec(path=policy_path)], schema=schema, gateway=gateway)


class TestEndToEnd:
    def test_two_builds_of_one_corpus_are_byte_identical(
        self, policy_path, card_auth_schema
    ) -> None:
        first = build(policy_path, card_auth_schema)
        second = build(policy_path, card_auth_schema)
        assert json.dumps(first.graph.as_dict(), sort_keys=True) == json.dumps(
            second.graph.as_dict(), sort_keys=True
        )
        assert first.manifest.identity.digest == second.manifest.identity.digest

    def test_the_attempt_limit_survives_as_one_triple_with_every_citation(
        self, policy_path, card_auth_schema
    ) -> None:
        result = build(policy_path, card_auth_schema)
        value = entity_id("Value", canonical_surface("Value", "3 authentication attempts"))
        limits = [t for t in result.graph.live if t.head == value and t.relation == "VALUE_IS"]

        assert len(limits) == 1
        assert limits[0].tail == "3"
        assert len(limits[0].spans) >= 3, "each phrasing of the limit should keep its own citation"
        assert "deterministic" in limits[0].methods

    def test_a_failure_with_no_stated_destination_invents_none(
        self, policy_path, card_auth_schema
    ) -> None:
        result = build(policy_path, card_auth_schema)
        failed = entity_id("Outcome", canonical_surface("Outcome", "FAILED"))

        assert any(t.tail == failed for t in result.graph.live if t.relation == "RETURNS")
        assert not [t for t in result.graph.live if t.head == failed and t.relation == "LEADS_TO"]
        assert any(
            q.kind == "integrity/outcome-destination" and failed in q.blocks
            for q in result.questions
        )

    def test_a_lone_model_claim_that_matters_is_held_for_review_not_admitted(
        self, policy_path, card_auth_schema
    ) -> None:
        result = build(policy_path, card_auth_schema)
        returns = [t for t in result.graph.triples if t.relation == "RETURNS"]
        assert returns
        assert all(t.status == "review" for t in returns)
        assert all(t.methods == {"llm"} for t in returns)

    def test_every_rejection_records_which_criterion_it_failed(
        self, policy_path, card_auth_schema
    ) -> None:
        result = build(policy_path, card_auth_schema)
        assert all(r.criterion and r.detail for r in result.rejections)

    def test_no_section_is_left_silently_unread(self, policy_path, card_auth_schema) -> None:
        result = build(policy_path, card_auth_schema)
        assert result.coverage.batches > 0
        assert result.coverage.silent == ()


class TestCoverageAudit:
    def test_a_section_that_returns_nothing_is_read_a_second_time(
        self, policy_path, core_schema
    ) -> None:
        class SilentGateway(ScriptedGateway):
            def json(self, **kwargs: Any) -> dict[str, Any]:
                self.calls.append(kwargs["label"])
                if kwargs["label"].startswith("glossary"):
                    return {"entities": []}
                return {"non_normative": False, "triples": []}

        _, passages = read_passages(policy_path)
        batch = batch_passages(passages, title="policy")[0]
        gateway = SilentGateway()

        result = extract_batch(
            batch, gateway=gateway, schema=core_schema, glossary=Glossary(entries=())
        )

        assert result.reread
        assert result.silent
        assert sum(1 for call in gateway.calls if call.endswith("/reread")) == 1


class TestOutputs:
    def test_a_build_writes_graph_quarantine_questions_and_manifest(
        self, tmp_path, policy_path, card_auth_schema
    ) -> None:
        result = build(policy_path, card_auth_schema)
        reports.write_build(result, tmp_path)

        for name in (
            reports.GRAPH_FILE,
            reports.QUARANTINE_FILE,
            reports.QUESTIONS_FILE,
            reports.MANIFEST_FILE,
            reports.REPORT_FILE,
        ):
            assert (tmp_path / name).exists(), name

    def test_an_answer_survives_a_rebuild_of_unchanged_text(
        self, tmp_path, policy_path, card_auth_schema
    ) -> None:
        result = build(policy_path, card_auth_schema)
        questions_file = tmp_path / reports.QUESTIONS_FILE
        reports.write_build(result, tmp_path)

        text = questions_file.read_text(encoding="utf-8")
        answered_text = text.replace("answer: ''", "answer: approve", 1)
        questions_file.write_text(answered_text, encoding="utf-8")
        decisions = review.read(questions_file)
        answered = [d for d in decisions.values() if d.answered]
        assert len(answered) == 1

        again = build(policy_path, card_auth_schema)
        reports.write_build(again, tmp_path, decisions=decisions)
        assert review.read(questions_file)[answered[0].question_id].answer == "approve"
        assert len(review.outstanding(again.questions, decisions)) == len(again.questions) - 1
