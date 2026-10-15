"""
ReachGuard — OpenAI-compatible LLM client and health checking.

Implements Contract Section 2, 7, 10:
- LLMClient for chat completions with tool-call parsing and plain-text fallback.
- Health check with 15-second cache and Ollama model validation.
- Sanitized error handling via LLMUnavailable without leaking API keys.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """Raised when the LLM service is unreachable, times out, or returns an error."""


class LLMClient:
    """Client for OpenAI-compatible chat completion APIs (Ollama, vLLM, OpenAI, etc.)."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout_s: float | None = None,
        provider: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else settings.LLM_BASE_URL).rstrip("/")
        self.model = model if model is not None else settings.LLM_MODEL
        self.api_key = api_key if api_key is not None else settings.LLM_API_KEY
        self.timeout_s = float(timeout_s if timeout_s is not None else settings.LLM_TIMEOUT_S)
        self.provider = (provider if provider is not None else settings.LLM_PROVIDER).lower()
        self.transport = transport

        # In-memory health cache: {"result": dict, "expires_at": float}
        self._health_cache: dict[str, Any] | None = None

    def _sanitize(self, message: str) -> str:
        """Strip API key from messages or log text to prevent leakage."""
        if self.api_key and self.api_key in message:
            return message.replace(self.api_key, "[REDACTED]")
        return message

    def _get_headers(self) -> dict[str, str]:
        """Build request headers, adding Authorization only if api_key is set."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key and self.api_key.strip():
            headers["Authorization"] = f"Bearer {self.api_key.strip()}"
        return headers

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send chat messages and return parsed content and tool calls.

        Returns:
            {
                "content": str | None,
                "tool_calls": [{"name": str, "arguments": dict}],
                "raw_finish_reason": str
            }
        Raises:
            LLMUnavailable on connection error, timeout, or non-200 status.
        """
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        headers = self._get_headers()

        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_s) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException as exc:
            msg = f"LLM request timed out after {self.timeout_s}s"
            logger.warning("%s: %s", msg, self._sanitize(str(exc)))
            raise LLMUnavailable(msg) from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            msg = f"LLM returned HTTP {status_code}"
            logger.warning("%s: %s", msg, self._sanitize(str(exc)))
            raise LLMUnavailable(msg) from exc
        except (httpx.RequestError, Exception) as exc:
            msg = f"Failed to connect to LLM at {self.base_url}"
            logger.warning("%s: %s", msg, self._sanitize(str(exc)))
            raise LLMUnavailable(msg) from exc

        choices = data.get("choices", [])
        if not choices:
            return {
                "content": None,
                "tool_calls": [],
                "raw_finish_reason": "stop",
            }

        first_choice = choices[0]
        msg_obj = first_choice.get("message", {})
        raw_finish_reason = str(first_choice.get("finish_reason") or "stop")
        content: str | None = msg_obj.get("content")

        tool_calls: list[dict[str, Any]] = []

        # 1. Parse standard OpenAI tool_calls
        raw_tool_calls = msg_obj.get("tool_calls") or []
        for tc in raw_tool_calls:
            fn = tc.get("function", {})
            fn_name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            if isinstance(raw_args, dict):
                parsed_args = raw_args
            else:
                try:
                    parsed_args = json.loads(raw_args)
                    if not isinstance(parsed_args, dict):
                        parsed_args = {}
                except (json.JSONDecodeError, TypeError, ValueError):
                    parsed_args = {}
            tool_calls.append({"name": str(fn_name), "arguments": parsed_args})

        # 2. Handle models that return tool call JSON as plain text in content
        if not tool_calls and content:
            parsed_text_tool = self._parse_tool_call_from_text(content)
            if parsed_text_tool:
                tool_calls.append(parsed_text_tool)
                content = None

        return {
            "content": content,
            "tool_calls": tool_calls,
            "raw_finish_reason": raw_finish_reason,
        }

    def _parse_tool_call_from_text(self, text: str) -> dict[str, Any] | None:
        """Detect and extract tool-call JSON formatted as plain text inside content."""
        clean = text.strip()

        # Unwrap markdown code fence if present
        if clean.startswith("```"):
            lines = clean.splitlines()
            if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
                clean = "\n".join(lines[1:-1]).strip()

        if not (clean.startswith("{") and clean.endswith("}")):
            return None

        try:
            parsed = json.loads(clean)
            if not isinstance(parsed, dict):
                return None

            # Support both ("name", "arguments") and ("tool", "parameters")
            name = parsed.get("name") or parsed.get("tool")
            if not name or not isinstance(name, str):
                return None

            raw_args = parsed.get("arguments")
            if raw_args is None:
                raw_args = parsed.get("parameters")

            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                    if not isinstance(args, dict):
                        args = {}
                except (json.JSONDecodeError, TypeError, ValueError):
                    args = {}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}

            return {"name": name, "arguments": args}
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    def health(self, fresh: bool = False) -> dict[str, Any]:
        """Check LLM reachable status with 15-second caching.

        Returns:
            {"provider": str, "model": str, "reachable": bool, "mode": "llm" | "deterministic"}
        """
        # If provider is "none", never make any network calls
        if self.provider == "none":
            return {
                "provider": "none",
                "model": self.model,
                "reachable": False,
                "mode": "deterministic",
            }

        now = time.monotonic()
        if (
            not fresh
            and self._health_cache is not None
            and now < self._health_cache["expires_at"]
        ):
            return dict(self._health_cache["result"])

        url = f"{self.base_url}/models"
        headers = self._get_headers()
        reachable = False

        try:
            with httpx.Client(transport=self.transport, timeout=3.0) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    reachable = self._check_model_in_response(data)
        except Exception as exc:  # noqa: BLE001
            logger.debug("LLM health check failed for %s: %s", self.base_url, self._sanitize(str(exc)))
            reachable = False

        mode = "llm" if reachable else "deterministic"
        result = {
            "provider": self.provider,
            "model": self.model,
            "reachable": reachable,
            "mode": mode,
        }

        # Cache for 15 seconds
        self._health_cache = {
            "result": result,
            "expires_at": now + 15.0,
        }
        return dict(result)

    def _check_model_in_response(self, data: Any) -> bool:
        """Validate model availability.

        For Ollama: requires configured model to appear in list (ignoring ':latest').
        For other providers: 200 OK from /models is sufficient.
        """
        if self.provider != "ollama":
            return True

        # Extract model IDs from response
        models_list: list[str] = []
        if isinstance(data, dict):
            items = data.get("data") or data.get("models") or []
            for item in items:
                if isinstance(item, dict):
                    m_id = item.get("id") or item.get("name")
                    if m_id:
                        models_list.append(str(m_id))
                elif isinstance(item, str):
                    models_list.append(item)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    m_id = item.get("id") or item.get("name")
                    if m_id:
                        models_list.append(str(m_id))
                elif isinstance(item, str):
                    models_list.append(item)

        cfg_normalized = self.model.removesuffix(":latest").lower()
        for m in models_list:
            if m.removesuffix(":latest").lower() == cfg_normalized:
                return True
        return False


# ── Module Singleton & Factory ─────────────────────────────────

_client_singleton: LLMClient | None = None


def get_client() -> LLMClient:
    """Return the singleton LLMClient configured from settings."""
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = LLMClient()
    return _client_singleton


def health() -> dict[str, Any]:
    """Check LLM health for FastAPI health check."""
    return get_client().health()
