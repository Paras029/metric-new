from __future__ import annotations

from pathlib import Path

from metric.corpus.furniture import find_furniture, strip_furniture
from metric.corpus.passages import passages_from_blocks, read_passages
from metric.corpus.readers.markdown import read_markdown
from metric.extract.batching import batch_passages
from metric.ontology.types import Document

TABLE = """\
## Tools

| Tool / API | When used | Example output |
|---|---|---|
| `authenticate_customer` | For each attempt | `AUTHENTICATED` / `FAILED` |
| `transfer_to_ccp` | After success or max retry | `TRANSFERRED` / `FAILED` |
"""

DOCUMENT = Document(id="d1", path="x.md", sha256="0" * 64, media_type="text/markdown")


class TestMarkdownReader:
    def test_each_table_row_becomes_its_own_block(self) -> None:
        rows = [b for b in read_markdown(TABLE, doc_label="tools") if b.kind == "table"]
        assert len(rows) == 2

    def test_every_cell_carries_its_column_header(self) -> None:
        first = next(b for b in read_markdown(TABLE, doc_label="tools") if b.kind == "table")
        assert "Tool / API: authenticate_customer" in first.text
        assert "When used: For each attempt" in first.text

    def test_code_spans_keep_their_identifier_intact(self) -> None:
        first = next(b for b in read_markdown(TABLE, doc_label="tools") if b.kind == "table")
        assert "authenticate_customer" in first.text

    def test_emphasis_is_unwrapped_without_touching_intraword_underscores(self) -> None:
        block = read_markdown("**A.** Call `transfer_to_ccp` now.", doc_label="d")[0]
        assert block.text == "A. Call transfer_to_ccp now."

    def test_rows_inherit_the_heading_path(self) -> None:
        first = next(b for b in read_markdown(TABLE, doc_label="tools") if b.kind == "table")
        assert first.heading_path == ("Tools",)


class TestFurniture:
    def test_a_short_line_repeating_is_treated_as_furniture(self) -> None:
        text = "\n\n".join(["Card Authentication Voice Bot | 1", "Real content here."] * 3)
        blocks = read_markdown(text, doc_label="d")
        furniture = find_furniture(blocks)
        assert "Card Authentication Voice Bot | 1" in furniture
        kept = strip_furniture(blocks, furniture)
        assert all(b.text != "Card Authentication Voice Bot | 1" for b in kept)

    def test_detection_needs_repetition_not_vocabulary(self) -> None:
        blocks = read_markdown("Card Authentication Voice Bot | 1\n\nReal content.", doc_label="d")
        assert find_furniture(blocks) == frozenset()


class TestPassages:
    def test_headings_do_not_become_passages(self) -> None:
        passages = passages_from_blocks(DOCUMENT, read_markdown(TABLE, doc_label="tools"))
        assert all(p.kind != "heading" for p in passages)

    def test_identity_survives_reflow(self) -> None:
        one = passages_from_blocks(DOCUMENT, read_markdown("A sentence here.", doc_label="d"))
        two = passages_from_blocks(DOCUMENT, read_markdown("A   sentence\nhere.", doc_label="d"))
        assert [p.id for p in one] == [p.id for p in two]

    def test_reading_the_policy_yields_passages_with_headings(self, policy_path: Path) -> None:
        _, passages = read_passages(policy_path)
        assert len(passages) > 30
        assert any("Operating procedure" in " ".join(p.heading_path) for p in passages)


class TestBatching:
    def test_no_passage_is_split_across_batches(self, policy_path: Path) -> None:
        _, passages = read_passages(policy_path)
        batches = batch_passages(passages, title="policy")
        cores = [p.id for batch in batches for p in batch.core]
        assert cores == [p.id for p in passages]

    def test_neighbouring_passages_are_visible_from_both_sides(self, policy_path: Path) -> None:
        _, passages = read_passages(policy_path)
        batches = batch_passages(passages, title="policy", budget_chars=900, min_chars=300)
        assert len(batches) > 2
        assert batches[0].before == ()
        assert batches[1].before == (batches[0].core[-1],)
        assert batches[0].after == (batches[1].core[0],)

    def test_batch_identity_depends_on_content_not_position(self, policy_path: Path) -> None:
        _, passages = read_passages(policy_path)
        first = batch_passages(passages, title="policy", budget_chars=900, min_chars=300)
        again = batch_passages(passages, title="other", budget_chars=900, min_chars=300)
        assert [b.id for b in first] == [b.id for b in again]

    def test_rendered_labels_cover_every_passage_in_the_window(self, policy_path: Path) -> None:
        _, passages = read_passages(policy_path)
        batch = batch_passages(passages, title="policy", budget_chars=900, min_chars=300)[1]
        rendered = batch.render()
        assert all(f"[{label}]" in rendered for label in batch.labels)
        assert len(batch.labels) == len(batch.core) + 2
