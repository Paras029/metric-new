"""Choosing a gateway from settings, in one place.

The CLI and the UI both build one, and an installation switches transport by editing a
line of YAML rather than by patching a call site. `provider: safechain` is the only edit
needed to move this pipeline inside the bank.
"""

from __future__ import annotations

from pathlib import Path

from metric.llm.cache import ResponseCache
from metric.llm.fixtures import FixtureGateway
from metric.llm.gateway import AnthropicGateway, Gateway, ModelConfig, ReplayGateway
from metric.settings import LLMSettings


def model_config(settings: LLMSettings) -> ModelConfig:
    return ModelConfig(
        model=settings.model, effort=settings.effort, max_tokens=settings.max_tokens
    )


def build_gateway(
    settings: LLMSettings,
    *,
    cache_path: Path | None = None,
    fixture_path: Path | None = None,
    replay: bool = False,
    use_case: str = "",
) -> Gateway:
    """The gateway this build should use.

    A fixture wins over everything: a corpus that names a recorded extraction is asking
    to be rebuilt from it, and reaching for the network in that case would make an
    offline build silently online.
    """
    if fixture_path is not None:
        return FixtureGateway.from_file(fixture_path)

    config = model_config(settings)
    cache = ResponseCache(root=cache_path) if cache_path else None

    if replay or settings.provider == "replay":
        if cache is None:
            raise ValueError("replay needs a cache directory")
        return ReplayGateway(cache, config=config)

    if settings.provider == "safechain":
        from metric.llm.safechain import SafeChainGateway

        return SafeChainGateway(config=config, cache=cache, use_case=use_case)

    if settings.provider == "fixture":
        raise ValueError("llm.provider is `fixture` but the corpus names no fixture file")

    return AnthropicGateway(config=config, cache=cache)
