"""The accuracy gate, and the claims it refuses to make.

Most of these are about what the gate will *not* do: clear a build on a self-marked
annotation, generalise past the sections someone actually read, or let a small sample
pass a high threshold on a point estimate.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import entity, triple

from metric.accuracy import (
    DEFAULT_GATE,
    AnnotationError,
    load_annotation,
    measure,
)
from metric.graph.model import build as build_graph
from metric.ontology.ids import canonical_name, entity_id

REPO = Path(__file__).resolve().parents[1]
GOLD = REPO / "annotations" / "card_auth.gold.yaml"

HEADER = """corpus: c.md
annotator: someone
independent: true
"""


def write(path: Path, body: str, header: str = HEADER) -> Path:
    path.write_text(header + body, encoding="utf-8")
    return path


def eid(entity_type: str, name: str) -> str:
    return entity_id(entity_type, canonical_name(name))


def graph_with(*pairs: tuple[str, str, str]):
    """A tiny graph of State -HAS_NEXT_STEP-> State triples, by name."""
    names = {n for head, _, tail in pairs for n in (head, tail)}
    entities = [entity(eid("State", n), "State", canonical=n) for n in sorted(names)]
    triples = [
        triple(eid("State", head), relation, eid("State", tail)) for head, relation, tail in pairs
    ]
    return build_graph(entities, triples)


def annotation(tmp_path: Path, *pairs: tuple[str, str, str], independent: bool = True):
    body = "triples:\n" + "".join(
        f'  - head: {{type: State, name: "{head}"}}\n'
        f"    relation: {relation}\n"
        f'    tail: {{type: State, name: "{tail}"}}\n'
        for head, relation, tail in pairs
    )
    header = f"corpus: c.md\nannotator: someone\nindependent: {str(independent).lower()}\n"
    return load_annotation(write(tmp_path / "gold.yaml", body, header))


class TestTheGoldFile:
    def test_the_shipped_annotation_loads(self) -> None:
        found = load_annotation(GOLD)
        assert found.triples
        assert found.covers

    def test_the_shipped_annotation_admits_it_is_not_independent(self) -> None:
        """It was written by the author of the extraction prompts, and says so."""
        assert load_annotation(GOLD).independent is False

    @pytest.mark.parametrize("missing", ["corpus", "annotator", "independent"])
    def test_provenance_is_required(self, tmp_path: Path, missing: str) -> None:
        header = "".join(
            line + "\n"
            for line in HEADER.strip().splitlines()
            if not line.startswith(missing)
        )
        with pytest.raises(AnnotationError, match=missing):
            load_annotation(write(tmp_path / "g.yaml", "triples: []\n", header))

    def test_an_annotation_with_no_triples_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(AnnotationError, match="annotates no triples"):
            load_annotation(write(tmp_path / "g.yaml", "triples: []\n"))


class TestScoring:
    def test_a_perfect_graph_scores_one(self, card_auth_schema, tmp_path: Path) -> None:
        graph = graph_with(("a", "HAS_NEXT_STEP", "b"))
        found = measure(
            graph, card_auth_schema, annotation(tmp_path, ("a", "HAS_NEXT_STEP", "b"))
        )
        assert found.overall.precision == 1.0
        assert found.overall.recall == 1.0
        assert found.invented == () and found.missed == ()

    def test_an_invented_fact_costs_precision_not_recall(
        self, card_auth_schema, tmp_path: Path
    ) -> None:
        graph = graph_with(("a", "HAS_NEXT_STEP", "b"), ("a", "HAS_NEXT_STEP", "c"))
        found = measure(
            graph, card_auth_schema, annotation(tmp_path, ("a", "HAS_NEXT_STEP", "b"))
        )
        assert found.overall.precision == 0.5
        assert found.overall.recall == 1.0
        assert len(found.invented) == 1

    def test_a_missed_fact_costs_recall_not_precision(
        self, card_auth_schema, tmp_path: Path
    ) -> None:
        graph = graph_with(("a", "HAS_NEXT_STEP", "b"))
        found = measure(
            graph,
            card_auth_schema,
            annotation(tmp_path, ("a", "HAS_NEXT_STEP", "b"), ("a", "HAS_NEXT_STEP", "c")),
        )
        assert found.overall.precision == 1.0
        assert found.overall.recall == 0.5

    def test_a_missed_fact_is_named_the_way_the_annotator_named_it(
        self, card_auth_schema, tmp_path: Path
    ) -> None:
        """The graph does not contain it, so the graph cannot name it.

        Printing a content hash sends a reader looking for an entity that does not exist.
        """
        graph = graph_with(("a", "HAS_NEXT_STEP", "b"))
        found = measure(
            graph, card_auth_schema, annotation(tmp_path, ("somewhere else", "HAS_NEXT_STEP", "b"))
        )
        assert found.missed[0][0] == "somewhere else"

    def test_a_relation_nobody_annotated_is_neither_right_nor_wrong(
        self, card_auth_schema, tmp_path: Path
    ) -> None:
        """Otherwise every unannotated relation in the graph scores as an invention."""
        graph = build_graph(
            [entity(eid("State", "a"), "State", canonical="a"), entity(eid("Tool", "t"), "Tool")],
            [
                triple(eid("State", "a"), "HAS_NEXT_STEP", eid("State", "a")),
                triple(eid("State", "a"), "USES_TOOL", eid("Tool", "t")),
            ],
        )
        found = measure(
            graph, card_auth_schema, annotation(tmp_path, ("a", "HAS_NEXT_STEP", "a"))
        )
        assert found.overall.precision == 1.0
        assert any("nobody annotated" in note for note in found.notes)

    def test_naming_disagreement_is_separated_from_invention(
        self, card_auth_schema, tmp_path: Path
    ) -> None:
        """The first real run scored 65% strict and 75% relaxed; the gap was all naming.

        Reporting only the strict number would have sent someone to fix an extractor that
        had read the sentence correctly and labelled the node differently.
        """
        graph = graph_with(("the sentence it appears in", "HAS_NEXT_STEP", "b"))
        found = measure(
            graph,
            card_auth_schema,
            annotation(tmp_path, ("Retry control", "HAS_NEXT_STEP", "b")),
        )
        assert found.overall.precision == 0.0
        assert found.relaxed.precision == 1.0
        assert len(found.naming) == 1


class TestTheGate:
    def test_a_small_sample_does_not_clear_a_high_threshold(
        self, card_auth_schema, tmp_path: Path
    ) -> None:
        """Precision 100% over two facts has a lower bound near 34%.

        The gate compares the interval's lower bound, so passing on two observations is
        not evidence of anything.
        """
        pairs = (("a", "HAS_NEXT_STEP", "b"), ("b", "HAS_NEXT_STEP", "c"))
        found = measure(graph_with(*pairs), card_auth_schema, annotation(tmp_path, *pairs))
        assert found.overall.precision == 1.0
        assert found.failures

    def test_a_self_marked_annotation_never_clears_a_build(
        self, card_auth_schema, tmp_path: Path
    ) -> None:
        """However good the numbers are. Two people sharing an assumption agree perfectly."""
        pairs = tuple((f"s{i}", "HAS_NEXT_STEP", f"s{i + 1}") for i in range(400))
        graph = graph_with(*pairs)
        marked = measure(graph, card_auth_schema, annotation(tmp_path, *pairs, independent=False))
        assert marked.failures == (), "a perfect graph should clear every threshold"
        assert marked.trustworthy is False

        honest = measure(graph, card_auth_schema, annotation(tmp_path, *pairs, independent=True))
        assert honest.trustworthy is True

    def test_a_98_percent_gate_needs_hundreds_of_annotated_facts(
        self, card_auth_schema, tmp_path: Path
    ) -> None:
        """Worth knowing before commissioning the annotation.

        Sixty facts, every one of them correct, still has a lower bound near 94% — under
        the high-materiality gate. The bar is a statement about how much reading someone
        has to do, not only about how good the pipeline has to be.
        """
        pairs = tuple((f"s{i}", "HAS_NEXT_STEP", f"s{i + 1}") for i in range(60))
        found = measure(graph_with(*pairs), card_auth_schema, annotation(tmp_path, *pairs))
        assert found.overall.precision == 1.0
        assert any("high-materiality" in failure for failure in found.failures)

    def test_high_materiality_carries_the_stricter_bar(self) -> None:
        assert DEFAULT_GATE["precision_high"] > DEFAULT_GATE["precision"]

    def test_precision_is_gated_harder_than_recall(self) -> None:
        """An invented fact fails an agent unjustly; a missing one is only a gap."""
        assert DEFAULT_GATE["precision"] > DEFAULT_GATE["recall"]


class TestTheRealCorpus:
    def test_the_build_is_scored_and_the_result_is_recorded(self, built) -> None:
        found = measure(built.graph, built.schema, load_annotation(GOLD))
        assert found.overall.predicted > 0
        assert found.overall.actual > 0
        assert found.trustworthy is False, "the shipped annotation is not independent"

    def test_the_disagreements_are_listed_not_just_counted(self, built) -> None:
        """A score with no defect list cannot be acted on."""
        found = measure(built.graph, built.schema, load_annotation(GOLD))
        assert len(found.invented) == found.overall.false_positive
        assert len(found.missed) == found.overall.false_negative

    def test_span_agreement_is_measured_separately(self, built) -> None:
        """A right fact cited to the wrong sentence is still a defect."""
        found = measure(built.graph, built.schema, load_annotation(GOLD))
        assert found.span_agreement.predicted > 0
