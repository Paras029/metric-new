"""Settings: the customisation surface, and the things it will not let you say."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from tests.conftest import triple

from metric.admit.grounding import locate
from metric.ontology.types import Span
from metric.reconcile.dedup import apply_witness_bar
from metric.settings import Settings, SettingsError, load_settings

REPO = Path(__file__).resolve().parents[1]


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


class TestLoading:
    def test_no_file_is_the_defaults(self) -> None:
        assert load_settings(None) == Settings()

    def test_the_shipped_file_matches_the_defaults(self) -> None:
        """metric.yaml documents the defaults. If it drifts it stops being documentation."""
        assert load_settings(REPO / "metric.yaml") == Settings()

    def test_a_partial_file_leaves_the_rest_alone(self, tmp_path: Path) -> None:
        settings = load_settings(write(tmp_path / "s.yaml", "corpus:\n  batch_chars: 3000\n"))
        assert settings.corpus.batch_chars == 3000
        assert settings.corpus.min_batch_chars == Settings().corpus.min_batch_chars
        assert settings.admission == Settings().admission

    def test_a_misspelled_key_is_refused_rather_than_ignored(self, tmp_path: Path) -> None:
        """Ignoring it would leave the operator believing they had changed something."""
        with pytest.raises(SettingsError, match="unknown keys"):
            load_settings(write(tmp_path / "s.yaml", "corpus:\n  batch_char: 1000\n"))

    def test_an_unknown_section_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(SettingsError, match="unknown sections"):
            load_settings(write(tmp_path / "s.yaml", "extraction:\n  x: 1\n"))

    def test_an_unknown_provider_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(SettingsError, match="not one of"):
            load_settings(write(tmp_path / "s.yaml", "llm:\n  provider: openai\n"))

    def test_a_batch_floor_above_its_ceiling_is_refused(self, tmp_path: Path) -> None:
        """No batch could ever be cut at a section boundary, so the setting is incoherent."""
        with pytest.raises(SettingsError, match="could ever be cut"):
            load_settings(
                write(tmp_path / "s.yaml", "corpus:\n  batch_chars: 100\n  min_batch_chars: 500\n")
            )


class TestIdentity:
    def test_different_settings_are_a_different_build(self) -> None:
        base = Settings()
        changed = replace(base, corpus=replace(base.corpus, batch_chars=3000))
        assert base.digest != changed.digest

    def test_the_same_settings_always_hash_the_same(self) -> None:
        assert Settings().digest == Settings().digest

    def test_the_settings_digest_reaches_the_build_identity(self, built) -> None:
        identity = built.result.manifest.identity
        assert identity.settings == built.settings.digest
        assert identity.settings in identity.as_dict()["settings"]


class TestSettingsReachTheStages:
    """A setting nothing reads is documentation, not configuration."""

    def test_the_quote_floor_is_what_decides_a_short_quote(self) -> None:
        text = "The agent must transfer the call."
        assert locate("transfer", text, min_quote_chars=4) is not None
        assert locate("transfer", text, min_quote_chars=20) is None

    def test_turning_the_witness_bar_off_admits_what_it_would_have_held(self) -> None:
        unwitnessed = _high(triple("State:a", "HAS_NEXT_STEP", "State:b"))
        assert apply_witness_bar([unwitnessed])[0].status == "review"
        assert apply_witness_bar([unwitnessed], enabled=False)[0].status == "admitted"

    def test_raising_the_bar_holds_a_fact_two_passages_already_support(self) -> None:
        both = _high(
            triple("State:a", "HAS_NEXT_STEP", "State:b"),
            spans=(
                Span(passage_id="p1", start=0, end=5, quote="one"),
                Span(passage_id="p2", start=0, end=5, quote="two"),
            ),
        )
        assert apply_witness_bar([both])[0].status == "admitted"
        assert apply_witness_bar([both], min_passages=3)[0].status == "review"

    def test_a_materiality_the_bar_does_not_name_passes_it(self) -> None:
        normal = replace(
            _high(triple("State:a", "HAS_NEXT_STEP", "State:b")), materiality="normal"
        )
        assert apply_witness_bar([normal])[0].status == "admitted"


def _high(base, spans=None):
    changed = replace(base, materiality="high", methods=frozenset({"llm"}))
    return replace(changed, spans=spans) if spans else changed
