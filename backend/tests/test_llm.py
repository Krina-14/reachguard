"""
Tests for backend/app/agent/llm.py.

Uses httpx.MockTransport to fake HTTP responses (unit tests for HTTP parsing).
Tests:
- normal answer
- tool call answer (standard OpenAI tool_calls)
- tool call as text (plain text JSON and markdown code block fallback)
- 500 error raises LLMUnavailable without key leakage
- timeout raises LLMUnavailable
- provider none returns deterministic mode without network call
- health check with Ollama model list matching and 15s cache
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.agent.llm import LLMClient, LLMUnavailable


def test_normal_answer() -> None:
    """Mock a standard chat completion response with content."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        req_body = json.loads(request.content)
        assert req_body["model"] == "test-model"
        assert req_body["temperature"] == 0.1
        assert req_body["stream"] is False

        resp_data = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Repository analysis is complete.",
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        return httpx.Response(200, json=resp_data)

    transport = httpx.MockTransport(handler)
    client = LLMClient(
        base_url="http://mock-llm/v1",
        model="test-model",
        transport=transport,
    )

    res = client.chat(messages=[{"role": "user", "content": "Analyze repo"}])
    assert res["content"] == "Repository analysis is complete."
    assert res["tool_calls"] == []
    assert res["raw_finish_reason"] == "stop"


def test_tool_call_answer() -> None:
    """Mock an OpenAI tool-call response."""
    def handler(request: httpx.Request) -> httpx.Response:
        resp_data = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "trace_paths",
                                    "arguments": json.dumps({"finding_id": "find-1"}),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        return httpx.Response(200, json=resp_data)

    transport = httpx.MockTransport(handler)
    client = LLMClient(
        base_url="http://mock-llm/v1",
        model="test-model",
        transport=transport,
    )

    res = client.chat(
        messages=[{"role": "user", "content": "Trace finding find-1"}],
        tools=[{"type": "function", "function": {"name": "trace_paths"}}],
    )
    assert res["content"] is None
    assert len(res["tool_calls"]) == 1
    assert res["tool_calls"][0] == {
        "name": "trace_paths",
        "arguments": {"finding_id": "find-1"},
    }
    assert res["raw_finish_reason"] == "tool_calls"


def test_tool_call_as_text() -> None:
    """Handle models that return tool call JSON as plain text inside content."""
    # Format A: {"name": ..., "arguments": ...}
    def handler_a(request: httpx.Request) -> httpx.Response:
        resp_data = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"name": "choke_points", "arguments": {"repo_id": "r1"}}',
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        return httpx.Response(200, json=resp_data)

    client_a = LLMClient(
        base_url="http://mock-llm/v1",
        model="test-model",
        transport=httpx.MockTransport(handler_a),
    )
    res_a = client_a.chat([{"role": "user", "content": "Show choke points"}])
    assert res_a["content"] is None
    assert len(res_a["tool_calls"]) == 1
    assert res_a["tool_calls"][0] == {
        "name": "choke_points",
        "arguments": {"repo_id": "r1"},
    }

    # Format B: {"tool": ..., "parameters": ...} wrapped in markdown code fence
    def handler_b(request: httpx.Request) -> httpx.Response:
        markdown_json = '```json\n{"tool": "score_finding", "parameters": {"finding_id": "f2"}}\n```'
        resp_data = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": markdown_json,
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        return httpx.Response(200, json=resp_data)

    client_b = LLMClient(
        base_url="http://mock-llm/v1",
        model="test-model",
        transport=httpx.MockTransport(handler_b),
    )
    res_b = client_b.chat([{"role": "user", "content": "Score finding"}])
    assert res_b["content"] is None
    assert len(res_b["tool_calls"]) == 1
    assert res_b["tool_calls"][0] == {
        "name": "score_finding",
        "arguments": {"finding_id": "f2"},
    }


def test_500_error_raises_llm_unavailable_and_masks_key() -> None:
    """Non-200 responses raise LLMUnavailable and never leak the API key."""
    secret_key = "sk-super-secret-key-12345"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == f"Bearer {secret_key}"
        return httpx.Response(500, text=f"Error with key {secret_key}")

    transport = httpx.MockTransport(handler)
    client = LLMClient(
        base_url="http://mock-llm/v1",
        model="test-model",
        api_key=secret_key,
        transport=transport,
    )

    with pytest.raises(LLMUnavailable) as exc_info:
        client.chat([{"role": "user", "content": "Hello"}])

    err_str = str(exc_info.value)
    assert secret_key not in err_str
    assert "LLM returned HTTP 500" in err_str


def test_timeout_raises_llm_unavailable() -> None:
    """Timeout exceptions raise LLMUnavailable."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Request timed out", request=request)

    transport = httpx.MockTransport(handler)
    client = LLMClient(
        base_url="http://mock-llm/v1",
        model="test-model",
        timeout_s=5,
        transport=transport,
    )

    with pytest.raises(LLMUnavailable) as exc_info:
        client.chat([{"role": "user", "content": "Hello"}])

    assert "timed out after 5.0s" in str(exc_info.value)


def test_provider_none_health() -> None:
    """When LLM_PROVIDER is 'none', health returns deterministic without network calls."""
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    client = LLMClient(
        provider="none",
        model="qwen2.5:7b-instruct",
        transport=httpx.MockTransport(handler),
    )

    h = client.health()
    assert h == {
        "provider": "none",
        "model": "qwen2.5:7b-instruct",
        "reachable": False,
        "mode": "deterministic",
    }
    assert called is False


def test_ollama_health_model_matching_and_cache() -> None:
    """Ollama health matches model name ignoring ':latest' suffix and caches for 15s."""
    requests_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests_count
        requests_count += 1
        assert request.url.path == "/v1/models"
        # Ollama models list with :latest suffix
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "qwen2.5:7b-instruct:latest"},
                    {"id": "llama3.2:3b"},
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = LLMClient(
        base_url="http://mock-llm/v1",
        provider="ollama",
        model="qwen2.5:7b-instruct",
        transport=transport,
    )

    # 1. First call: fetches from mock
    h1 = client.health(fresh=True)
    assert h1["reachable"] is True
    assert h1["mode"] == "llm"
    assert requests_count == 1

    # 2. Second call: served from cache (no extra request)
    h2 = client.health()
    assert h2["reachable"] is True
    assert requests_count == 1

    # 3. Model not in list -> reachable False, mode deterministic
    client_missing = LLMClient(
        base_url="http://mock-llm/v1",
        provider="ollama",
        model="nonexistent-model",
        transport=transport,
    )
    h_missing = client_missing.health(fresh=True)
    assert h_missing["reachable"] is False
    assert h_missing["mode"] == "deterministic"
