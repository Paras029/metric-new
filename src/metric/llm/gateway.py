"""The single place a model is called.

Every model call in the pipeline goes through `json()`: one system prompt, one user
prompt, one JSON schema the response must satisfy. Extraction code never sees a
message list, a content block or a stop reason, so the shape of a prompt and the
shape of a request cannot drift apart.

Two deliberate omissions:

*Sampling controls.* `temperature`, `top_p` and `top_k` are rejected by current
models. Nothing here pretends otherwise; determinism comes from the response cache
(see `cache.py`), and residual variation is measured rather than assumed away.

*Server-side fallbacks.* A refusal fallback would silently answer from a different
model. The model id is part of build identity, so a silent substitution would make
two builds claim the same identity while meaning different things. A refusal raises
instead, and the build stops.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from metric.llm.cache import CacheMiss, ResponseCache, request_key

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "high"
DEFAULT_MAX_TOKENS = 16000


class LLMError(RuntimeError):
    """A model call that cannot be turned into a usable JSON object."""


class ModelRefusal(LLMError):
    """The model declined the request. Not retried: a retry would only hide it."""


@dataclass(frozen=True, slots=True)
class ModelConfig:
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    max_tokens: int = DEFAULT_MAX_TOKENS

    @property
    def identity(self) -> str:
        """What the manifest records. Any change here is a different build."""
        return f"{self.model}?effort={self.effort}&max_tokens={self.max_tokens}"


class Gateway(Protocol):
    @property
    def identity(self) -> str: ...

    def json(
        self, *, system: str, prompt: str, schema: dict[str, Any], label: str
    ) -> dict[str, Any]:
        """Return the model's response as an object validated against `schema`.

        `label` names the call site and appears in errors; it never reaches the model,
        so it cannot perturb the request key.
        """
        ...


class AnthropicGateway:
    """Calls Claude, recording every response in the cache before returning it."""

    def __init__(
        self,
        *,
        config: ModelConfig | None = None,
        cache: ResponseCache | None = None,
        client: Any | None = None,
    ) -> None:
        self._config = config or ModelConfig()
        self._cache = cache
        self._client = client

    @property
    def identity(self) -> str:
        return self._config.identity

    def json(
        self, *, system: str, prompt: str, schema: dict[str, Any], label: str
    ) -> dict[str, Any]:
        payload = _payload(self._config, system=system, prompt=prompt, schema=schema)
        key = request_key(payload)

        if self._cache is not None:
            cached = self._cache.get(key)
            if cached is not None:
                return cached

        response = self._call(payload, label=label)

        if self._cache is not None:
            self._cache.put(key, request=payload, response=response)
        return response

    def _call(self, payload: dict[str, Any], *, label: str) -> dict[str, Any]:
        import json as _json

        client = self._client or _default_client()
        message = client.messages.create(
            model=payload["model"],
            max_tokens=payload["max_tokens"],
            system=payload["system"],
            messages=[{"role": "user", "content": payload["prompt"]}],
            output_config={
                "effort": payload["effort"],
                "format": {"type": "json_schema", "schema": payload["schema"]},
            },
        )

        if message.stop_reason == "refusal":
            detail = getattr(message.stop_details, "explanation", "") or ""
            raise ModelRefusal(f"{label}: model declined the request. {detail}".strip())
        if message.stop_reason == "max_tokens":
            raise LLMError(
                f"{label}: response hit max_tokens ({payload['max_tokens']}); "
                "the batch is too large to answer in one call"
            )

        text = next((block.text for block in message.content if block.type == "text"), None)
        if text is None:
            raise LLMError(f"{label}: response contained no text block")

        try:
            parsed = _json.loads(text)
        except ValueError as exc:
            raise LLMError(f"{label}: response was not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise LLMError(f"{label}: response was {type(parsed).__name__}, expected an object")
        return parsed


class ReplayGateway:
    """Serves only what the cache already holds.

    Used by tests and by any rebuild that must not reach the network: a miss is an
    error, because silently calling the model would make the rebuild a new build.
    """

    def __init__(self, cache: ResponseCache, *, config: ModelConfig | None = None) -> None:
        self._cache = cache
        self._config = config or ModelConfig()

    @property
    def identity(self) -> str:
        return self._config.identity

    def json(
        self, *, system: str, prompt: str, schema: dict[str, Any], label: str
    ) -> dict[str, Any]:
        key = request_key(_payload(self._config, system=system, prompt=prompt, schema=schema))
        cached = self._cache.get(key)
        if cached is None:
            raise CacheMiss(f"{label}: no recorded response for request {key[:12]}")
        return cached


def _payload(
    config: ModelConfig, *, system: str, prompt: str, schema: dict[str, Any]
) -> dict[str, Any]:
    return {
        "model": config.model,
        "effort": config.effort,
        "max_tokens": config.max_tokens,
        "system": system,
        "prompt": prompt,
        "schema": schema,
    }


def _default_client() -> Any:
    try:
        from anthropic import Anthropic
    except ImportError as exc:  # pragma: no cover - depends on the install extra
        raise LLMError(
            "the anthropic SDK is not installed; install metric[llm] or pass a client"
        ) from exc
    return Anthropic()
