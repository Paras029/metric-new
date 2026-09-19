"""The enterprise gateway: the adaptation is transport, and nothing else moves.

These tests exist because the claim "switching to SafeChain is a settings change" is
easy to make and easy to break. Each one pins a property that would have to hold for it
to be true inside the bank.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from metric.llm.cache import ResponseCache
from metric.llm.gateway import AnthropicGateway, LLMError, ModelConfig, ModelRefusal
from metric.llm.safechain import SafeChainGateway
from metric.llm.select import build_gateway
from metric.settings import LLMSettings

SCHEMA: dict[str, Any] = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
ANSWER = {"ok": True}


class NativeClient:
    """A client with SafeChain's own `invoke`."""

    def __init__(self, response: Any = None) -> None:
        self.response = response if response is not None else {"content": json.dumps(ANSWER)}
        self.requests: list[dict[str, Any]] = []

    def invoke(self, request: dict[str, Any]) -> Any:
        self.requests.append(request)
        return self.response


class _Completions:
    def __init__(self, holder: OpenAIStyleClient) -> None:
        self.holder = holder

    def create(self, **kwargs: Any) -> dict[str, Any]:
        self.holder.calls.append(kwargs)
        return {"choices": [{"message": {"content": json.dumps(ANSWER)}}]}


class _Chat:
    def __init__(self, holder: OpenAIStyleClient) -> None:
        self.completions = _Completions(holder)


class OpenAIStyleClient:
    """A client behind SafeChain's OpenAI-compatible route."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.chat = _Chat(self)


def call(gateway: Any) -> dict[str, Any]:
    return gateway.json(system="sys", prompt="say ok", schema=SCHEMA, label="test")


class TestTransport:
    def test_the_native_route_returns_the_parsed_object(self) -> None:
        assert call(SafeChainGateway(client=NativeClient())) == ANSWER

    def test_the_openai_compatible_route_returns_the_same_object(self) -> None:
        assert call(SafeChainGateway(client=OpenAIStyleClient())) == ANSWER

    def test_entitlement_metadata_travels_with_every_call(self) -> None:
        """SafeChain attributes and entitles by these; a call without them is rejected."""
        client = NativeClient()
        gateway = SafeChainGateway(client=client, app_id="APP123", use_case="card_auth")
        call(gateway)
        assert client.requests[0]["metadata"] == {
            "app_id": "APP123",
            "use_case": "card_auth",
        }

    def test_the_schema_is_sent_so_the_model_cannot_invent_a_relation(self) -> None:
        client = NativeClient()
        call(SafeChainGateway(client=client))
        assert client.requests[0]["response_format"]["json_schema"] == SCHEMA

    def test_a_client_that_is_neither_shape_is_an_error_not_a_guess(self) -> None:
        with pytest.raises(LLMError, match="neither"):
            call(SafeChainGateway(client=object()))

    def test_an_envelope_with_no_text_is_an_error_not_an_empty_extraction(self) -> None:
        """Guessing wrong here yields a silent corpus that looks like a quiet policy."""
        with pytest.raises(LLMError, match="no text"):
            call(SafeChainGateway(client=NativeClient({"usage": {"tokens": 3}})))

    def test_a_block_list_response_is_joined(self) -> None:
        response = {"content": [{"type": "text", "text": json.dumps(ANSWER)}]}
        assert call(SafeChainGateway(client=NativeClient(response))) == ANSWER


class TestItBehavesLikeTheDirectGateway:
    def test_a_refusal_raises_rather_than_falling_back(self) -> None:
        """A silent substitution would let two builds claim one identity."""
        with pytest.raises(ModelRefusal):
            call(SafeChainGateway(client=NativeClient({"stop_reason": "refusal"})))

    def test_the_cache_key_is_the_same_as_the_vendor_route(self, tmp_path: Path) -> None:
        """So a graph built here and one built against the vendor SDK are one build."""
        cache = ResponseCache(root=tmp_path / "cache")
        config = ModelConfig(model="m", effort="high", max_tokens=100)
        call(SafeChainGateway(config=config, cache=cache, client=NativeClient()))

        served = AnthropicGateway(config=config, cache=cache, client=None)
        assert call(served) == ANSWER  # no client is touched: the cache answers

    def test_the_gateway_identity_records_the_entitlement(self) -> None:
        identity = SafeChainGateway(app_id="APP1", use_case="uc").identity
        assert identity.startswith("safechain:")
        assert "APP1" in identity and "uc" in identity

    def test_a_different_entitlement_is_a_different_build(self) -> None:
        assert SafeChainGateway(app_id="A").identity != SafeChainGateway(app_id="B").identity


class TestSelection:
    def test_the_provider_setting_is_the_whole_switch(self, tmp_path: Path) -> None:
        settings = LLMSettings(provider="safechain")
        gateway = build_gateway(settings, cache_path=tmp_path / "c", use_case="uc")
        assert isinstance(gateway, SafeChainGateway)

    def test_a_fixture_beats_the_provider_so_an_offline_build_stays_offline(
        self, tmp_path: Path
    ) -> None:
        fixture = tmp_path / "f.json"
        fixture.write_text(json.dumps({"entities": [], "triples": []}), encoding="utf-8")
        gateway = build_gateway(
            LLMSettings(provider="safechain"), cache_path=None, fixture_path=fixture
        )
        assert not isinstance(gateway, SafeChainGateway)

    def test_replay_needs_a_cache_to_replay_from(self) -> None:
        with pytest.raises(ValueError, match="cache"):
            build_gateway(LLMSettings(provider="replay"), cache_path=None)
