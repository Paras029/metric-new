"""Reading a workflow off pictures, including one split across several of them.

The split case is the one that matters. A workflow too long for a page is exported as
tiles, and the whole question is whether an arrow that runs off the edge of one tile is
picked up by the next — so most of these build a two-page diagram and check the join.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from metric.corpus.readers.errors import UnreadableDocument
from metric.diagram.images import MAX_BYTES, Image, load, load_all, natural_key, order
from metric.diagram.read import read_diagrams
from metric.diagram.structure import Structure, audit, clean, merge
from metric.diagram.triples import as_candidates, as_passage, read_into_corpus

PAGE_ONE: dict[str, Any] = {
    "states": [
        {"id": "S1", "name": "Opening", "reached_via": "Start", "next_decisions": ["D1"]},
        {
            "id": "S2",
            "name": "Authentication attempts",
            "reached_via": "D1=proceed",
            "next_decisions": ["D2"],
            "tools": ["authenticate_customer"],
        },
        {
            "id": "S3",
            "name": "Failed authentication and retry",
            "reached_via": "D2=FAILED",
            "continues": "A",
        },
        {"id": "S4", "name": "Successful authentication", "reached_via": "D2=AUTHENTICATED"},
    ],
    "decisions": [
        {"id": "D1", "name": "ready", "outcomes": ["proceed", "abandon"], "at_state": "S1"},
        {
            "id": "D2",
            "name": "authentication result",
            "outcomes": ["FAILED", "AUTHENTICATED"],
            "at_state": "S2",
        },
    ],
}

PAGE_TWO: dict[str, Any] = {
    "states": [
        {"id": "S1", "name": "Failed authentication and retry", "reached_via": "A"},
        {"id": "S2", "name": "Maximum retry reached", "reached_via": "S1", "next_states": ["S3"]},
        {"id": "S3", "name": "Transfer to CCP", "terminal": True, "tools": ["transfer_to_ccp"]},
    ],
    "decisions": [],
}

JOINED: dict[str, Any] = {
    "states": [
        {"id": "S1", "name": "Opening", "reached_via": "Start", "next_decisions": ["D1"]},
        {
            "id": "S2",
            "name": "Authentication attempts",
            "reached_via": "D1=proceed",
            "next_decisions": ["D2"],
            "tools": ["authenticate_customer"],
        },
        {
            "id": "S3",
            "name": "Failed authentication and retry",
            "reached_via": "D2=FAILED",
            "next_states": ["S5"],
        },
        {"id": "S4", "name": "Successful authentication", "reached_via": "D2=AUTHENTICATED",
         "next_states": ["S6"]},
        {"id": "S5", "name": "Maximum retry reached", "next_states": ["S6"]},
        {"id": "S6", "name": "Transfer to CCP", "terminal": True, "tools": ["transfer_to_ccp"]},
        {"id": "S7", "name": "Abandoned", "reached_via": "D1=abandon", "terminal": True},
    ],
    "decisions": [
        {"id": "D1", "name": "ready", "outcomes": ["proceed", "abandon"], "at_state": "S1"},
        {
            "id": "D2",
            "name": "authentication result",
            "outcomes": ["FAILED", "AUTHENTICATED"],
            "at_state": "S2",
        },
    ],
}


class VisionGateway:
    """Answers by call label, and records whether the pictures were actually attached."""

    identity = "scripted/vision"

    def __init__(self, answers: dict[str, Any], *, fail: tuple[str, ...] = ()) -> None:
        self.answers = answers
        self.fail = fail
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def json(self, *, system, prompt, schema, label, images=()):
        self.calls.append((label, tuple(i.name for i in images)))
        for prefix in self.fail:
            if label.startswith(prefix):
                raise RuntimeError("the model refused")
        for key, answer in self.answers.items():
            if label.startswith(key):
                return answer
        return {"states": [], "decisions": []}


def picture(name: str) -> Image:
    return Image(name=name, media_type="image/png", data=name.encode())


def _png(path: Path, width: int, height: int) -> None:
    from PIL import Image as Pillow

    Pillow.new("RGB", (width, height), "white").save(path)


class TestOrdering:
    def test_page_ten_sorts_after_page_two(self) -> None:
        """A string sort puts flow-10 before flow-2, and the join assumes page order."""
        paths = [Path(f"flow-{n}.png") for n in (10, 2, 1)]
        assert [p.name for p in order(paths)] == ["flow-1.png", "flow-2.png", "flow-10.png"]

    def test_the_key_is_stable_for_names_without_numbers(self) -> None:
        assert natural_key(Path("a.png")) < natural_key(Path("b.png"))


class TestLoading:
    def test_a_non_image_is_refused_with_the_formats_it_reads(self, tmp_path: Path) -> None:
        path = tmp_path / "notes.txt"
        path.write_text("x", encoding="utf-8")
        with pytest.raises(UnreadableDocument, match="not an image format"):
            load(path)

    def test_an_empty_file_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "flow.png"
        path.write_bytes(b"")
        with pytest.raises(UnreadableDocument, match="empty"):
            load(path)

    def test_one_bad_page_does_not_lose_the_others(self, tmp_path: Path) -> None:
        """Eight tiles with one corrupt file should still give seven tiles of workflow."""
        good = tmp_path / "flow-1.png"
        _png(good, 32, 24)
        truncated = tmp_path / "flow-2.png"
        truncated.write_bytes(good.read_bytes()[:20])
        wrong_type = tmp_path / "flow-3.txt"
        wrong_type.write_text("not a picture", encoding="utf-8")

        images, refused = load_all([good, truncated, wrong_type])
        assert [i.name for i in images] == ["flow-1.png"]
        assert len(refused) == 2, refused
        assert any("could not be decoded" in reason for reason in refused)

    def test_an_oversized_image_without_pillow_is_refused_not_sent(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Failing here beats failing per-call after the text has already been read."""
        import builtins

        real = builtins.__import__

        def no_pillow(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "PIL":
                raise ImportError("no pillow")
            return real(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_pillow)
        path = tmp_path / "huge.png"
        path.write_bytes(b"\x89PNG" + b"0" * (MAX_BYTES + 1))
        with pytest.raises(UnreadableDocument, match="Pillow is not installed"):
            load(path)


class TestTheAudit:
    """Every check has to be a property the graph needs to be walkable, not an opinion."""

    def test_an_empty_reading_says_so(self) -> None:
        assert audit(Structure()) == ("Nothing was read from the diagrams at all: "
                                      "no states and no decisions.",)

    def test_an_outcome_that_lands_nowhere_is_named(self) -> None:
        found = clean(
            {
                "states": [{"id": "S1", "name": "a", "reached_via": "Start"}],
                "decisions": [{"id": "D1", "name": "d", "outcomes": ["yes", "no"]}],
            }
        )
        problems = audit(found)
        assert any('"yes" leads nowhere' in p for p in problems)
        assert any('"no" leads nowhere' in p for p in problems)

    def test_a_branch_with_one_arrow_is_not_a_branch(self) -> None:
        found = clean(
            {
                "states": [{"id": "S1", "name": "a", "reached_via": "Start"}],
                "decisions": [{"id": "D1", "name": "d", "outcomes": ["only"]}],
            }
        )
        assert any("only one outcome" in p for p in audit(found))

    def test_a_missing_start_is_named(self) -> None:
        found = clean({"states": [{"id": "S1", "name": "a"}], "decisions": []})
        assert any("No state is marked as the start" in p for p in audit(found))

    def test_an_arrow_off_the_page_that_nothing_picks_up_is_named(self) -> None:
        found = clean(
            {
                "states": [
                    {"id": "S1", "name": "a", "reached_via": "Start", "continues": "S9"}
                ],
                "decisions": [],
            }
        )
        assert any("continuing at S9" in p for p in audit(found))

    def test_a_sound_graph_has_nothing_to_say(self) -> None:
        assert audit(clean(JOINED)) == ()


class TestCleaning:
    def test_an_entry_with_no_usable_id_is_dropped_not_invented(self) -> None:
        """A generated id would be indistinguishable from one read off a box."""
        found = clean({"states": [{"name": "nameless"}, {"id": "S1", "name": "a"}]})
        assert [s.id for s in found.states] == ["S1"]

    def test_a_blank_name_is_kept_because_the_box_is_still_there(self) -> None:
        found = clean({"states": [{"id": "S1", "name": ""}]})
        assert len(found.states) == 1

    def test_which_image_each_entry_came_from_is_recorded(self) -> None:
        found = clean(PAGE_ONE, seen_in="flow-1.png")
        assert all(s.seen_in == ("flow-1.png",) for s in found.states)


class TestMerging:
    def test_a_repair_replaces_what_it_names(self) -> None:
        base = clean({"states": [{"id": "S1", "name": "a"}]})
        repair = clean({"states": [{"id": "S1", "name": "a", "reached_via": "Start"}]})
        assert merge(base, repair).states[0].reached_via == "Start"

    def test_a_repair_never_removes(self) -> None:
        """A quieter second look is a worse reading, not a correction.

        Letting it delete is how a repair pass shrinks the graph every time it runs.
        """
        base = clean({"states": [{"id": "S1", "name": "a"}, {"id": "S2", "name": "b"}]})
        merged = merge(base, clean({"states": [{"id": "S1", "name": "a"}]}))
        assert {s.id for s in merged.states} == {"S1", "S2"}


class TestReadingAcrossPages:
    def test_each_page_is_read_on_its_own_then_joined(self) -> None:
        gateway = VisionGateway(
            {"diagram/read[flow-1": PAGE_ONE, "diagram/read[flow-2": PAGE_TWO,
             "diagram/join": JOINED}
        )
        read_diagrams([picture("flow-1.png"), picture("flow-2.png")], gateway=gateway)

        labels = [label for label, _ in gateway.calls]
        assert labels[0].startswith("diagram/read[flow-1")
        assert labels[1].startswith("diagram/read[flow-2")
        assert "diagram/join" in labels

    def test_each_page_is_read_alone_and_the_join_sees_them_all(self) -> None:
        """One picture at a time: a model given eight tiles summarises, given one it counts."""
        gateway = VisionGateway(
            {"diagram/read[flow-1": PAGE_ONE, "diagram/read[flow-2": PAGE_TWO,
             "diagram/join": JOINED}
        )
        read_diagrams([picture("flow-1.png"), picture("flow-2.png")], gateway=gateway)

        by_label = dict(gateway.calls)
        assert by_label["diagram/read[flow-1.png]"] == ("flow-1.png",)
        assert by_label["diagram/read[flow-2.png]"] == ("flow-2.png",)
        assert by_label["diagram/join"] == ("flow-1.png", "flow-2.png")

    def test_the_joined_workflow_spans_both_pages(self) -> None:
        gateway = VisionGateway(
            {"diagram/read[flow-1": PAGE_ONE, "diagram/read[flow-2": PAGE_TWO,
             "diagram/join": JOINED}
        )
        reading = read_diagrams([picture("flow-1.png"), picture("flow-2.png")], gateway=gateway)

        names = {s.name for s in reading.structure.states}
        assert "Opening" in names, "page one"
        assert "Transfer to CCP" in names, "page two"
        assert reading.sound

    def test_a_single_page_is_not_sent_for_joining(self) -> None:
        gateway = VisionGateway({"diagram/read": JOINED})
        read_diagrams([picture("flow.png")], gateway=gateway)
        assert not any(label == "diagram/join" for label, _ in gateway.calls)

    def test_a_page_that_cannot_be_read_is_reported_and_the_rest_go_through(self) -> None:
        gateway = VisionGateway(
            {"diagram/read[flow-2": PAGE_TWO}, fail=("diagram/read[flow-1",)
        )
        reading = read_diagrams([picture("flow-1.png"), picture("flow-2.png")], gateway=gateway)
        assert any("flow-1.png could not be read" in note for note in reading.notes)
        assert not reading.structure.empty

    def test_nothing_readable_gives_an_empty_structure_not_a_guess(self) -> None:
        gateway = VisionGateway({}, fail=("diagram/",))
        reading = read_diagrams([picture("a.png")], gateway=gateway)
        assert reading.structure.empty
        assert not reading.sound


class TestRepair:
    def test_the_audit_findings_go_back_with_the_pictures_still_attached(self) -> None:
        broken = {
            "states": [{"id": "S1", "name": "a", "reached_via": "Start"}],
            "decisions": [{"id": "D1", "name": "d", "outcomes": ["yes", "no"], "at_state": "S1"}],
        }
        fixed = {
            "states": [
                {"id": "S2", "name": "b", "reached_via": "D1=yes"},
                {"id": "S3", "name": "c", "reached_via": "D1=no", "terminal": True},
            ],
            "decisions": [],
        }
        gateway = VisionGateway({"diagram/read": broken, "diagram/repair": fixed})
        reading = read_diagrams([picture("flow.png")], gateway=gateway)

        repair = next(call for call in gateway.calls if call[0].startswith("diagram/repair"))
        assert repair[1] == ("flow.png",), "the repair needs the picture, not just the graph"
        assert reading.repairs == 1
        assert {s.name for s in reading.structure.states} == {"a", "b", "c"}

    def test_a_repair_that_fixes_nothing_stops_rather_than_looping(self) -> None:
        broken = {
            "states": [{"id": "S1", "name": "a", "reached_via": "Start"}],
            "decisions": [{"id": "D1", "name": "d", "outcomes": ["yes", "no"]}],
        }
        gateway = VisionGateway({"diagram/read": broken, "diagram/repair": {}})
        reading = read_diagrams([picture("flow.png")], gateway=gateway)
        assert reading.repairs == 1
        assert reading.remaining

    def test_what_could_not_be_settled_is_listed_not_guessed_at(self) -> None:
        gateway = VisionGateway(
            {
                "diagram/read": {
                    "states": [{"id": "S1", "name": "a", "reached_via": "Start"}],
                    "decisions": [{"id": "D1", "name": "d", "outcomes": ["yes", "no"]}],
                },
                "diagram/repair": {},
            }
        )
        reading = read_diagrams([picture("flow.png")], gateway=gateway)
        assert not reading.sound
        assert any("could not be settled" in note for note in reading.notes)


class TestProvenance:
    def test_what_was_read_becomes_a_passage_a_quote_can_be_found_in(self) -> None:
        """A picture has no sentences, so the reading of it becomes the text."""
        found = clean(JOINED)
        passage = as_passage("flow.png", found, doc_id="d")
        assert "box: Opening" in passage.text
        assert "arrow: FAILED" in passage.text
        assert passage.kind == "image"

    def test_every_candidate_cites_a_line_of_that_passage(self) -> None:
        found = clean(JOINED)
        passage = as_passage("flow.png", found, doc_id="d")
        lines = set(passage.text.splitlines())
        candidates = as_candidates(found, passage=passage, use_case="Card auth")
        assert candidates
        for candidate in candidates:
            assert candidate.quote in lines, candidate.quote
            assert candidate.passage_id == passage.id

    def test_a_diagram_fact_is_marked_as_read_from_a_picture(self) -> None:
        """So the witness bar can tell it from a sentence somebody wrote."""
        found = clean(JOINED)
        passage = as_passage("flow.png", found, doc_id="d")
        assert all(c.method == "vision" for c in as_candidates(found, passage=passage))

    def test_the_structural_relations_are_read_and_nothing_else(self) -> None:
        """A drawing shows where the journey goes. It does not state a rule."""
        found = clean(JOINED)
        passage = as_passage("flow.png", found, doc_id="d")
        relations = {c.relation for c in as_candidates(found, passage=passage, use_case="U")}
        assert relations <= {
            "STARTS_AT", "HAS_NEXT_STEP", "OFFERS_DECISION", "HAS_OUTCOME",
            "LEADS_TO", "IS_TERMINAL", "USES_TOOL",
        }
        assert not any(r.startswith("RULE_") for r in relations)

    def test_the_branch_and_where_each_outcome_lands_both_come_through(self) -> None:
        found = clean(JOINED)
        passage = as_passage("flow.png", found, doc_id="d")
        edges = {
            (c.head, c.relation, c.tail)
            for c in as_candidates(found, passage=passage, use_case="U")
        }
        assert ("authentication result", "HAS_OUTCOME", "FAILED") in edges
        assert ("FAILED", "LEADS_TO", "Failed authentication and retry") in edges
        assert ("Transfer to CCP", "IS_TERMINAL", "true") in edges

    def test_a_corpus_of_several_pictures_yields_one_passage_each(self) -> None:
        passages, candidates = read_into_corpus(
            [("flow-1.png", clean(PAGE_ONE)), ("flow-2.png", clean(PAGE_TWO))], doc_id="d"
        )
        assert [p.location for p in passages] == ["flow-1.png (as read)", "flow-2.png (as read)"]
        assert candidates
