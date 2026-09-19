"""Calling the model through an enterprise gateway instead of the vendor SDK.

Inside American Express, model traffic does not go to a vendor endpoint. It goes through
SafeChain, which owns authentication, entitlement, routing, prompt and response
inspection, and the audit record. A pipeline that calls `anthropic.Anthropic()` directly
is not deployable there, whatever else is true about it.

This is the whole of the adaptation, and that is the design: `Gateway` is one method
taking a system prompt, a user prompt and a JSON schema, so an installation supplies its
own transport and nothing else in the package changes. Extraction, admission, the cache
and build identity are all written against the protocol, not against a vendor.

Three things are kept exactly as the direct gateway has them, because they are properties
of the evaluation rather than of the transport:

- **The cache sits above the transport.** The request key is computed from the same
  payload either way, so a graph built here and a graph built against the vendor SDK are
  the same build when the model and prompts match — and are recorded as different builds
  when they do not.
- **A refusal raises.** No fallback model, no retry. A silent substitution would let two
  builds claim one identity while meaning different things.
- **Sampling controls are absent**, for the same reason as in `gateway.py`.

`client` is injected. The SafeChain SDK is an internal package that will not import
outside the bank, so this module imports it lazily and only when no client was supplied,
which keeps the tests and the open repository runnable. The two supported client shapes
are the ones the SDK actually exposes: an OpenAI-compatible `chat.completions.create`,
and a native `invoke` taking a request mapping. Anything else is supplied pre-wrapped.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from metric.llm.cache import ResponseCache, request_key
from metric.llm.gateway import LLMError, ModelConfig, ModelRefusal, build_payload

DEFAULT_ENDPOINT_ENV = "SAFECHAIN_ENDPOINT"
DEFAULT_APP_ID_ENV = "SAFECHAIN_APP_ID"


class SafeChainGateway:
    """A `Gateway` whose transport is the bank's model gateway.

    `use_case` and `app_id` are not decoration: SafeChain attributes and entitles calls
    by them, and they end up in the audit record that a model risk review will ask for.
    They are part of this gateway's identity for the same reason the model id is — a
    build made under a different entitlement was made under different constraints.
    """

    def __init__(
        self,
        *,
        config: ModelConfig | None = None,
        cache: ResponseCache | None = None,
        client: Any | None = None,
        use_case: str = "",
        app_id: str = "",
        endpoint: str = "",
    ) -> None:
        self._config = config or ModelConfig()
        self._cache = cache
        self._client = client
        self._use_case = use_case
        self._app_id = app_id or os.environ.get(DEFAULT_APP_ID_ENV, "")
        self._endpoint = endpoint or os.environ.get(DEFAULT_ENDPOINT_ENV, "")

    @property
    def identity(self) -> str:
        parts = [f"safechain:{self._config.identity}"]
        if self._app_id:
            parts.append(f"app={self._app_id}")
        if self._use_case:
            parts.append(f"use_case={self._use_case}")
        return "&".join(parts)

    def json(
        self, *, system: str, prompt: str, schema: dict[str, Any], label: str
    ) -> dict[str, Any]:
        payload = build_payload(self._config, system=system, prompt=prompt, schema=schema)
        key = request_key(payload)

        if self._cache is not None:
            cached = self._cache.get(key)
            if cached is not None:
                return cached

        response = _parse(self._send(payload, label=label), label=label)

        if self._cache is not None:
            self._cache.put(key, request=payload, response=response)
        return response

    def _send(self, payload: dict[str, Any], *, label: str) -> str:
        client = self._client if self._client is not None else _default_client(self._endpoint)
        request = {
            "model": payload["model"],
            "max_tokens": payload["max_tokens"],
            "system": payload["system"],
            "messages": [{"role": "user", "content": payload["prompt"]}],
            "response_format": {"type": "json_schema", "json_schema": payload["schema"]},
            "metadata": {"app_id": self._app_id, "use_case": self._use_case},
        }

        invoke: Callable[..., Any] | None = getattr(client, "invoke", None)
        if callable(invoke):
            return _text_of(invoke(request), label=label)

        completions = getattr(getattr(client, "chat", None), "completions", None)
        if completions is not None:
            return _text_of(
                completions.create(
                    model=request["model"],
                    max_tokens=request["max_tokens"],
                    messages=[
                        {"role": "system", "content": payload["system"]},
                        {"role": "user", "content": payload["prompt"]},
                    ],
                    response_format=request["response_format"],
                    metadata=request["metadata"],
                ),
                label=label,
            )

        raise LLMError(
            f"{label}: the SafeChain client exposes neither `invoke` nor "
            "`chat.completions.create`; wrap it before passing it in"
        )


def _text_of(response: Any, *, label: str) -> str:
    """Pull the assistant text out of whichever response shape came back.

    SafeChain passes vendor responses through with its own envelope around them, and the
    envelope differs by route. Each branch here is a shape the gateway actually returns;
    an unrecognised one is an error rather than a guess, because guessing wrong yields an
    empty extraction that looks like a silent corpus.
    """
    if isinstance(response, str):
        return response

    if isinstance(response, dict):
        if response.get("refusal") or response.get("stop_reason") == "refusal":
            raise ModelRefusal(f"{label}: SafeChain reported a refusal")
        for path in (
            ("content",),
            ("output", "text"),
            ("choices", 0, "message", "content"),
            ("data", "content"),
        ):
            found = _dig(response, path)
            if isinstance(found, str) and found:
                return found
            if isinstance(found, list):
                text = "".join(
                    block.get("text", "")
                    for block in found
                    if isinstance(block, dict) and block.get("type") in (None, "text")
                )
                if text:
                    return text
        raise LLMError(f"{label}: SafeChain response had no text; keys were {sorted(response)}")

    choices = getattr(response, "choices", None)
    if choices:
        content = getattr(getattr(choices[0], "message", None), "content", None)
        if isinstance(content, str) and content:
            return content

    raise LLMError(f"{label}: unrecognised SafeChain response of type {type(response).__name__}")


def _dig(document: Any, path: tuple[Any, ...]) -> Any:
    for step in path:
        if isinstance(step, int):
            if not isinstance(document, list) or len(document) <= step:
                return None
            document = document[step]
        else:
            if not isinstance(document, dict) or step not in document:
                return None
            document = document[step]
    return document


def _parse(text: str, *, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise LLMError(f"{label}: response was not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMError(f"{label}: response was {type(parsed).__name__}, expected an object")
    return parsed


def _default_client(endpoint: str) -> Any:  # pragma: no cover - internal package
    try:
        # An internal package: it exists on the bank's index and nowhere else, so
        # neither the type checker nor CI can see it.
        from safechain import SafeChainClient  # type: ignore[import-not-found]
    except ImportError as exc:
        raise LLMError(
            "the SafeChain SDK is not installed. It is an internal package: install it "
            "from the bank's index, or construct SafeChainGateway with `client=` in "
            "environments that cannot reach it"
        ) from exc
    return SafeChainClient(endpoint=endpoint) if endpoint else SafeChainClient()
