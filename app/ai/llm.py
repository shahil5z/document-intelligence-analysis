"""OpenAI-compatible chat-completions client over HTTP (httpx2) with a hard timeout.

Works with OpenAI and other servers exposing ``POST {base_url}/chat/completions``.
Errors are reported as ``LLMError`` with generic messages: the API key, prompts and
response bodies are never logged or included in exceptions.
"""

import logging
import time
from collections.abc import Sequence
from typing import Any

import httpx2

from app.ai.base import ChatMessage
from app.ai.errors import LLMError
from app.core.metrics import LLM_LATENCY

logger = logging.getLogger(__name__)


class OpenAICompatibleLLMProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float,
        max_output_tokens: int,
        temperature: float,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._client = httpx2.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx2.Timeout(timeout_seconds),
            transport=transport,
        )

    @property
    def model_name(self) -> str:
        return self._model

    def complete(self, messages: Sequence[ChatMessage]) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [dict(message) for message in messages],
            "temperature": self._temperature,
            "max_tokens": self._max_output_tokens,
        }
        started = time.perf_counter()
        try:
            content, body = self._post(payload)
        except LLMError:
            LLM_LATENCY.labels("error").observe(time.perf_counter() - started)
            raise
        elapsed = time.perf_counter() - started
        LLM_LATENCY.labels("ok").observe(elapsed)
        usage = body.get("usage") if isinstance(body, dict) else None
        # Field names avoid "token" so the log redactor (app/core/logging.py) keeps them.
        logger.info(
            "llm.completed",
            extra={
                "model": self._model,
                "duration_ms": round(elapsed * 1000),
                "usage_prompt": (usage or {}).get("prompt_tokens"),
                "usage_completion": (usage or {}).get("completion_tokens"),
            },
        )
        return content

    def close(self) -> None:
        self._client.close()

    def _post(self, payload: dict[str, Any]) -> tuple[str, Any]:
        try:
            response = self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except httpx2.TimeoutException as exc:
            logger.warning("llm.timeout", extra={"model": self._model})
            raise LLMError("the language model did not respond in time") from exc
        except httpx2.HTTPStatusError as exc:
            logger.warning(
                "llm.http_error",
                extra={"model": self._model, "status_code": exc.response.status_code},
            )
            raise LLMError("the language model request was rejected") from exc
        except httpx2.HTTPError as exc:
            logger.warning(
                "llm.transport_error",
                extra={"model": self._model, "error_type": type(exc).__name__},
            )
            raise LLMError("the language model is unreachable") from exc
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            logger.warning("llm.malformed_response", extra={"model": self._model})
            raise LLMError("the language model returned an unexpected response") from exc
        if not isinstance(content, str):
            raise LLMError("the language model returned an unexpected response")
        return content, body
