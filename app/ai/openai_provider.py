"""OpenAI-backed implementations of the provider protocols.

Not exercised against the real OpenAI API in DIP1; the unit tests use a fake client.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.ai.base import ChatMessage

if TYPE_CHECKING:
    from openai import OpenAI
    from openai.types.chat import ChatCompletionMessageParam


def _to_openai_message(message: ChatMessage) -> "ChatCompletionMessageParam":
    if message["role"] == "system":
        return {"role": "system", "content": message["content"]}
    if message["role"] == "assistant":
        return {"role": "assistant", "content": message["content"]}
    return {"role": "user", "content": message["content"]}


class OpenAIChatProvider:
    def __init__(self, client: "OpenAI", model: str) -> None:
        self._client = client
        self._model = model

    def complete(self, messages: Sequence[ChatMessage]) -> str:
        payload = [_to_openai_message(message) for message in messages]
        response = self._client.chat.completions.create(model=self._model, messages=payload)
        return response.choices[0].message.content or ""


class OpenAIEmbeddingProvider:
    def __init__(self, client: "OpenAI", model: str) -> None:
        self._client = client
        self._model = model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.embeddings.create(model=self._model, input=list(texts))
        ordered = sorted(response.data, key=lambda item: item.index)
        return [list(item.embedding) for item in ordered]
