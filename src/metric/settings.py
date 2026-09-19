"""Every tunable in one place.

Each stage of the pipeline has numbers in it — how big a batch is, how short a quote
may be, how many paths to walk, how much a carried state binding is worth. Left as
module constants they are invisible to the person who has to defend them, and changing
one means editing code and losing the connection to the build it applied to.

Here they are one YAML file, loaded once, threaded to the call sites and recorded in
the build manifest. A build that used different settings is a different build and says
so, which is the same rule the schema, prompts and model already follow.

Defaults are what the code used before this file existed, so an absent `metric.yaml`
changes nothing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

import yaml


class SettingsError(Exception):
    """Raised when a settings file is malformed or names something unknown."""


@dataclass(frozen=True, slots=True)
class CorpusSettings:
    """Reading documents into passages."""

    batch_chars: int = 6000
    min_batch_chars: int = 1500
    furniture_min_repeats: int = 3
    furniture_max_chars: int = 90
    context_passages: int = 1


@dataclass(frozen=True, slots=True)
class AdmissionSettings:
    """What a candidate has to survive to become a fact."""

    min_quote_chars: int = 8
    check_polarity: bool = True
    check_value: bool = True
    numeric_word_tolerance: bool = True


@dataclass(frozen=True, slots=True)
class WitnessSettings:
    """When a high-materiality fact may stand on a single model reading.

    Turning this off makes every extraction admissible and removes the review queue's
    reason to exist. It is here because some corpora are already human-authored, not
    because it is a knob to reach for.
    """

    enabled: bool = True
    materiality: str = "high"
    min_passages: int = 2


@dataclass(frozen=True, slots=True)
class ScenarioSettings:
    """Walking the graph for journeys."""

    max_depth: int = 12
    max_paths: int = 500
    default_revisits: int = 3
    reach_for_uncovered: bool = True


@dataclass(frozen=True, slots=True)
class BindingSettings:
    """Placing an observed turn in the graph.

    `allow_inference` and `allow_carry` exist for a real choice: an installation that
    only wants to grade what the agent itself narrated turns both off and gets
    `none` for every unchecked turn, which is stricter and smaller.
    """

    allow_inference: bool = True
    allow_carry: bool = True
    confidence: dict[str, float] = field(
        default_factory=lambda: {
            "checkpoint": 1.0,
            "inferred": 0.8,
            "carried": 0.6,
            "ambiguous": 0.4,
            "none": 0.0,
        }
    )


@dataclass(frozen=True, slots=True)
class LLMSettings:
    """Which model, through which gateway."""

    provider: str = "anthropic"
    model: str = "claude-opus-5"
    effort: str = "high"
    max_tokens: int = 16000
    cache: str = ".metric/llm-cache"


@dataclass(frozen=True, slots=True)
class EnrichSettings:
    """How base scenarios are crossed with presentation factors."""

    arrangement: str = "crossed"
    adverse_run: bool = True
    seed: int = 0


@dataclass(frozen=True, slots=True)
class Settings:
    corpus: CorpusSettings = field(default_factory=CorpusSettings)
    admission: AdmissionSettings = field(default_factory=AdmissionSettings)
    witness: WitnessSettings = field(default_factory=WitnessSettings)
    scenario: ScenarioSettings = field(default_factory=ScenarioSettings)
    binding: BindingSettings = field(default_factory=BindingSettings)
    llm: LLMSettings = field(default_factory=LLMSettings)
    enrich: EnrichSettings = field(default_factory=EnrichSettings)

    @property
    def digest(self) -> str:
        """Part of build identity: different settings, different build."""
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_SECTIONS: dict[str, Any] = {
    "corpus": CorpusSettings,
    "admission": AdmissionSettings,
    "witness": WitnessSettings,
    "scenario": ScenarioSettings,
    "binding": BindingSettings,
    "llm": LLMSettings,
    "enrich": EnrichSettings,
}

_PROVIDERS = frozenset({"anthropic", "safechain", "fixture", "replay"})
_ARRANGEMENTS = frozenset({"crossed", "embedded"})


def load_settings(path: Path | None) -> Settings:
    """Read a settings file, or take the defaults when there is none."""
    if path is None:
        return Settings()

    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    if not isinstance(document, dict):
        raise SettingsError(f"{path} does not contain a YAML mapping")

    unknown = set(document) - set(_SECTIONS)
    if unknown:
        raise SettingsError(
            f"{path}: unknown sections {sorted(unknown)}; expected {sorted(_SECTIONS)}"
        )

    settings = Settings()
    for name, section in _SECTIONS.items():
        raw = document.get(name)
        if raw is None:
            continue
        if not isinstance(raw, dict):
            raise SettingsError(f"{path}: {name} must be a mapping")
        settings = replace(settings, **{name: _section(section, raw, name, path)})

    _validate(settings, path)
    return settings


def _section(kind: Any, raw: dict[str, Any], name: str, path: Path) -> Any:
    known = {f.name for f in fields(kind)}
    unknown = set(raw) - known
    if unknown:
        raise SettingsError(
            f"{path}: {name} has unknown keys {sorted(unknown)}; expected {sorted(known)}"
        )
    return kind(**raw)


def _validate(settings: Settings, path: Path) -> None:
    if settings.llm.provider not in _PROVIDERS:
        raise SettingsError(
            f"{path}: llm.provider {settings.llm.provider!r} is not one of "
            f"{sorted(_PROVIDERS)}"
        )
    if settings.enrich.arrangement not in _ARRANGEMENTS:
        raise SettingsError(
            f"{path}: enrich.arrangement {settings.enrich.arrangement!r} is not one of "
            f"{sorted(_ARRANGEMENTS)}"
        )
    if settings.corpus.min_batch_chars > settings.corpus.batch_chars:
        raise SettingsError(
            f"{path}: corpus.min_batch_chars ({settings.corpus.min_batch_chars}) exceeds "
            f"corpus.batch_chars ({settings.corpus.batch_chars}), so no batch could ever be "
            "cut at a section boundary. Lowering one usually means lowering both"
        )
    if settings.admission.min_quote_chars < 1:
        raise SettingsError(f"{path}: admission.min_quote_chars must be at least 1")
    if settings.witness.min_passages < 1:
        raise SettingsError(f"{path}: witness.min_passages must be at least 1")
