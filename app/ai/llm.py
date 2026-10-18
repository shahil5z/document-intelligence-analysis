"""OpenAI-compatible chat-completions client over HTTP (httpx2) with a hard timeout.

Works with OpenAI and other servers exposing ``POST {base_url}/chat/completions``.
Errors are reported as ``LLMError`` with generic messages: the API key, prompts and
response bodies are never logged or included in exceptions.
"""

import logging
import time
from collections.abc import Mapping, Sequence
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
        structured_output: bool = True,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._model = model
        # Flipped to False after the endpoint rejects response_format once (some
        # OpenAI-compatible servers and older models do not support json_schema).
        self._structured_output = structured_output
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

    def complete(
        self, messages: Sequence[ChatMessage], *, json_schema: Mapping[str, Any] | None = None
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [dict(message) for message in messages],
            "temperature": self._temperature,
            "max_tokens": self._max_output_tokens,
        }
        structured = json_schema is not None and self._structured_output
        if structured:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "grounded_answer", "strict": True, "schema": json_schema},
            }
        started = time.perf_counter()
        try:
            try:
                content, body = self._post(payload)
            except _RejectedRequestError:
                if not structured:
                    raise LLMError("the language model request was rejected") from None
                # 400/422 with response_format: retry once as a plain request, and stop
                # sending it from this client (the prompt still asks for JSON).
                logger.warning("llm.structured_output_unsupported", extra={"model": self._model})
                self._structured_output = False
                payload.pop("response_format")
                try:
                    content, body = self._post(payload)
                except _RejectedRequestError:
                    raise LLMError("the language model request was rejected") from None
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
                "structured_output": structured and self._structured_output,
                "finish_reason": _finish_reason(body),
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
            status = exc.response.status_code
            logger.warning("llm.http_error", extra={"model": self._model, "status_code": status})
            if status in (400, 422):
                raise _RejectedRequestError from exc
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
        if content is None:
            # Structured outputs report a safety refusal in message.refusal with content
            # null; the caller treats an empty reply as "no grounded answer".
            refusal = body["choices"][0]["message"].get("refusal")
            logger.warning("llm.no_content", extra={"model": self._model, "refusal": bool(refusal)})
            return "", body
        if not isinstance(content, str):
            raise LLMError("the language model returned an unexpected response")
        return content, body


class _RejectedRequestError(Exception):
    """HTTP 400/422 from the endpoint (possibly an unsupported parameter)."""


def _finish_reason(body: Any) -> str | None:
    try:
        reason = body["choices"][0].get("finish_reason")
    except (KeyError, IndexError, TypeError, AttributeError):
        return None
    return reason if isinstance(reason, str) else None
