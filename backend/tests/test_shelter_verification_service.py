"""Verify shelter_verification_service handles the tool-call loop correctly.

We mock the OpenAI client + Tavily HTTP layer so the tests don't need real API keys.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from app.services import shelter_verification_service as svs_module
from app.services.shelter_verification_service import ShelterVerificationService


def _make_settings() -> Settings:
    return Settings(
        openai_api_key="test-key",
        tavily_api_key="test-tavily",
        shelter_verification_timeout_seconds=10,
        shelter_verification_max_tool_calls=2,
    )


class _FakeToolCall:
    def __init__(self, call_id: str, query: str) -> None:
        self.id = call_id
        self.type = "function"
        self.function = SimpleNamespace(
            name="web_search",
            arguments=json.dumps({"query": query}),
        )


class _FakeMessage:
    def __init__(
        self,
        *,
        content: str | None = None,
        tool_calls: list[_FakeToolCall] | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message: _FakeMessage) -> None:
        self.message = message


class _FakeResponse:
    def __init__(self, message: _FakeMessage) -> None:
        self.choices = [_FakeChoice(message)]


class _FakeCompletions:
    def __init__(self, messages: list[_FakeMessage]) -> None:
        self._messages = messages
        self._index = 0

    async def create(self, **_kwargs: Any) -> _FakeResponse:
        message = self._messages[min(self._index, len(self._messages) - 1)]
        self._index += 1
        return _FakeResponse(message)


class _FakeChat:
    def __init__(self, messages: list[_FakeMessage]) -> None:
        self.completions = _FakeCompletions(messages)


class _FakeOpenAI:
    def __init__(self, messages: list[_FakeMessage]) -> None:
        self.chat = _FakeChat(messages)


def _install_fake_openai(monkeypatch: pytest.MonkeyPatch, messages: list[_FakeMessage]) -> None:
    monkeypatch.setattr(
        svs_module,
        "AsyncOpenAI",
        lambda **_kwargs: _FakeOpenAI(messages),
    )


async def _fake_tavily_search(
    self: ShelterVerificationService,
    _client: Any,
    query: str,
) -> list[dict[str, Any]]:
    return [
        {
            "title": f"{query} 官方介紹",
            "url": "https://example.com/shelter",
            "snippet": f"{query} 是一個真實存在的收容所。",
        }
    ]


def test_verify_returns_candidate_on_successful_tool_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_payload = {
        "verified": True,
        "canonical_name": "測試狗園",
        "entity_type": "私人狗園",
        "address": "新北市",
        "website": "https://example.com",
        "facebook_url": "https://fb.com/test",
        "aliases": ["測試A", "測試B"],
        "introduction": "一個測試狗園",
        "evidence_urls": ["https://example.com/shelter"],
    }
    messages = [
        _FakeMessage(content=None, tool_calls=[_FakeToolCall("call_1", "測試狗園")]),
        _FakeMessage(content=json.dumps(final_payload), tool_calls=None),
    ]
    _install_fake_openai(monkeypatch, messages)
    monkeypatch.setattr(
        ShelterVerificationService,
        "_tavily_search",
        _fake_tavily_search,
    )

    service = ShelterVerificationService(_make_settings())
    verified, candidate, reason = asyncio.run(service.verify("測試狗園"))

    assert verified is True
    assert reason == ""
    assert candidate is not None
    assert candidate.canonical_name == "測試狗園"
    assert "測試A" in candidate.aliases
    assert candidate.evidence_urls == ["https://example.com/shelter"]


def test_verify_rejects_response_without_evidence_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_payload = {
        "verified": True,
        "canonical_name": "幻覺狗園",
        "evidence_urls": [],
    }
    messages = [
        _FakeMessage(content=None, tool_calls=[_FakeToolCall("call_1", "幻覺狗園")]),
        _FakeMessage(content=json.dumps(final_payload), tool_calls=None),
    ]
    _install_fake_openai(monkeypatch, messages)
    monkeypatch.setattr(
        ShelterVerificationService,
        "_tavily_search",
        _fake_tavily_search,
    )

    service = ShelterVerificationService(_make_settings())
    verified, candidate, reason = asyncio.run(service.verify("幻覺狗園"))

    assert verified is False
    assert candidate is None
    assert reason == "no_evidence_urls"


def test_verify_propagates_model_rejection_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_payload = {"verified": False, "reason": "找不到任何相關資料"}
    messages = [
        _FakeMessage(content=None, tool_calls=[_FakeToolCall("call_1", "假狗園")]),
        _FakeMessage(content=json.dumps(final_payload), tool_calls=None),
    ]
    _install_fake_openai(monkeypatch, messages)
    monkeypatch.setattr(
        ShelterVerificationService,
        "_tavily_search",
        _fake_tavily_search,
    )

    service = ShelterVerificationService(_make_settings())
    verified, candidate, reason = asyncio.run(service.verify("假狗園"))

    assert verified is False
    assert candidate is None
    assert reason == "找不到任何相關資料"


def test_is_available_requires_both_api_keys() -> None:
    settings_no_tavily = Settings(openai_api_key="k", tavily_api_key=None)
    settings_no_openai = Settings(openai_api_key=None, tavily_api_key="k")
    settings_both = Settings(openai_api_key="k", tavily_api_key="k")

    assert ShelterVerificationService(settings_no_tavily).is_available() is False
    assert ShelterVerificationService(settings_no_openai).is_available() is False
    assert ShelterVerificationService(settings_both).is_available() is True
