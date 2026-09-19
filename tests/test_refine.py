"""Naming, pruning and section scope — the three things that made the graph legible.

Between them they took the working build from 20 rules to 5 and from 49 open questions
to 35, without changing a single fact the accuracy gate scores.
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import entity, triple

from metric.corpus.passages import read_passages
from metric.corpus.scope import Scope, apply_scope
from metric.ontology.ids import canonical_name, entity_id
from metric.ontology.schema import load_schema
from metric.refine.inert import prune
from metric.refine.names import needs_work, refine

REPO = Path(__file__).resolve().parents[1]
POLICY = REPO / "grounding" / "07-card-authentication-policy.md"


def rule(name: str, surfaces: tuple[str, ...] = ()):
    made = entity(entity_id("Rule", canonical_name(name)), "Rule", canonical=name)
    from dataclasses import replace

    return replace(made, surfaces=frozenset(surfaces or (name,)))


class TestWhatCountsAsAName:
    def test_a_short_noun_phrase_is_a_name(self) -> None:
        assert needs_work(rule("Retry control")) == ""

    def test_a_sentence_is_not(self) -> None:
        assert needs_work(rule("The bot must not perform any other servicing activity"))

    def test_a_tool_keeps_its_own_identifier(self) -> None:
        tool = entity(entity_id("Tool", "authenticate_customer"), "Tool",
                      canonical="authenticate_customer")
        assert needs_work(tool) == ""

    def test_a_literal_is_never_renamed(self) -> None:
        """A Turn's wording is content, not a name."""
        turn = entity(entity_id("Value", "3"), "Value", canonical="3")
        assert needs_work(turn) == ""


class TestLabelRenaming:
    def test_a_labelled_rule_takes_its_own_label(self) -> None:
        """Policy documents name their own rules; no model is needed to see that."""
        subject = rule(
            "No servicing: Do not answer or execute additional servicing requests",
            ("**No servicing:** Do not answer or execute additional servicing requests",),
        )
        found = refine([subject], [])
        assert [r.after for r in found.renames] == ["No servicing"]
        assert found.renames[0].method == "label"

    def test_renaming_moves_every_triple_with_it(self) -> None:
        """Identity is a content hash of the name, so a rename is an id change."""
        subject = rule(
            "Retry control: Enforce a hard maximum of 3 attempts",
            ("**Retry control:** Enforce a hard maximum of 3 attempts",),
        )
        action = entity(entity_id("Action", "retry"), "Action", canonical="retry")
        triples = [triple(subject.id, "RULE_FORBIDS", action.id)]

        found = refine([subject, action], triples)
        renamed = next(e for e in found.entities if e.type == "Rule")
        assert renamed.id != subject.id
        assert found.triples[0].head == renamed.id

    def test_two_rules_that_land_on_one_name_are_merged(self) -> None:
        first = rule("No servicing: do not service", ("**No servicing:** do not service",))
        second = rule(
            "No servicing: do not answer servicing requests",
            ("**No servicing:** do not answer servicing requests",),
        )
        found = refine([first, second], [])
        assert len(found.entities) == 1
        assert found.merges

    def test_an_unlabelled_sentence_is_reported_not_mangled(self) -> None:
        """Without a model there is nothing safe to do but say so."""
        found = refine([rule("The bot does not perform any additional servicing itself")], [])
        assert found.renames == ()
        assert found.unresolved
        assert any("no model was available" in note for note in found.notes)


class TestInertRules:
    def test_a_rule_that_states_only_itself_is_pruned(self, card_auth_schema) -> None:
        """It requires, forbids and bounds nothing, so nothing could be checked against it."""
        subject = rule("Never exceeds 3 attempts")
        triples = [
            triple(subject.id, "RULE_STATES", "Never exceeds 3 attempts", kind="literal"),
            triple(subject.id, "HAS_SEVERITY", "error", kind="literal"),
        ]
        found = prune([subject], triples, card_auth_schema)
        assert found.entities == ()
        assert [i.name for i in found.removed] == ["Never exceeds 3 attempts"]

    def test_a_rule_that_forbids_something_is_kept(self, card_auth_schema) -> None:
        subject = rule("No servicing")
        action = entity(entity_id("Action", "servicing"), "Action", canonical="servicing")
        triples = [triple(subject.id, "RULE_FORBIDS", action.id)]
        found = prune([subject, action], triples, card_auth_schema)
        assert found.removed == ()

    def test_a_rule_something_is_governed_by_is_kept(self, card_auth_schema) -> None:
        """Its clause was missed, but it is attached to a place where that can be noticed."""
        subject = rule("Retry control")
        state = entity(entity_id("State", "retry"), "State", canonical="retry")
        triples = [
            triple(state.id, "GOVERNED_BY", subject.id),
            triple(subject.id, "RULE_STATES", "text", kind="literal"),
        ]
        found = prune([subject, state], triples, card_auth_schema)
        assert found.removed == ()

    def test_what_is_pruned_is_named_not_silently_dropped(self, card_auth_schema) -> None:
        subject = rule("Some summary restatement")
        triples = [triple(subject.id, "RULE_STATES", "the text", kind="literal")]
        found = prune([subject], triples, card_auth_schema)
        assert found.removed[0].states == "the text"
        assert "restatement" in found.note or "restatements" in found.note


class TestSectionScope:
    def test_no_scope_reads_everything(self) -> None:
        _, passages = read_passages(POLICY)
        assert len(apply_scope(passages, Scope()).passages) == len(passages)

    def test_excluding_the_commentary_drops_only_the_commentary(self) -> None:
        """The policy file carries this repo's own notes about why it is a good corpus.

        Written in the same imperative voice, so the extractor read eight Rules out of
        them — well-formed, correctly cited, governing nothing, one human question each.
        """
        _, passages = read_passages(POLICY)
        scoped = apply_scope(
            passages, Scope(exclude=("Why this document is a good phase-1 target",))
        )
        assert len(scoped.dropped) == 10
        assert all("Why this document" in " ".join(p.heading_path) for p in scoped.dropped)
        assert scoped.note

    def test_a_section_can_be_named_by_its_number(self) -> None:
        _, passages = read_passages(POLICY)
        scoped = apply_scope(passages, Scope(include=("3",)))
        assert scoped.passages
        assert all(
            any(h.startswith("3.") or h.startswith("3 ") for h in p.heading_path)
            for p in scoped.passages
        )

    def test_a_scope_matching_nothing_keeps_nothing_and_says_so(self) -> None:
        _, passages = read_passages(POLICY)
        scoped = apply_scope(passages, Scope(include=("no such section",)))
        assert scoped.passages == ()
        assert scoped.note


class TestOnTheRealCorpus:
    def test_the_commentary_no_longer_becomes_policy(self, built) -> None:
        names = {e.canonical for e in built.graph.entities}
        assert not any("ingestion" in n or "first_corpus" in n for n in names)

    def test_no_rule_in_the_graph_asserts_nothing(self, built) -> None:
        schema = load_schema(built.spec.schema_path, built.spec.extension_path)
        checkable = {n for n, s in schema.relations.items() if s.checks is not None}
        attached = {t.tail for t in built.graph.live if t.relation == "GOVERNED_BY"}
        working = {t.head for t in built.graph.live if t.relation in checkable}
        for entity_ in built.graph.entities:
            if entity_.type != "Rule":
                continue
            assert entity_.id in working or entity_.id in attached, entity_.canonical

    def test_the_pruned_rules_are_one_question_not_nine(self, built) -> None:
        inert = [q for q in built.result.questions if q.kind == "refine/inert"]
        assert len(inert) == 1
        assert "rules state nothing checkable" in inert[0].heading
