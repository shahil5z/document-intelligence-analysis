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
    """OpenAI SDK chat adapter from DIP1. ``/ask`` uses ``app.ai.llm`` (HTTP) instead."""

    def __init__(self, client: "OpenAI", model: str) -> None:
        self._client = client
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    def complete(self, messages: Sequence[ChatMessage]) -> str:
        payload = [_to_openai_message(message) for message in messages]
        response = self._client.chat.completions.create(model=self._model, messages=payload)
        return response.choices[0].message.content or ""


class OpenAIEmbeddingProvider:
    """OpenAI SDK embedding adapter from DIP1. Not selectable via EMBEDDING_PROVIDER:
    the ``document_chunks.embedding`` column is fixed at the local model's dimension."""

    def __init__(self, client: "OpenAI", model: str, dimension: int = 1536) -> None:
        self._client = client
        self._model = model
        self._dimension = dimension

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.embeddings.create(model=self._model, input=list(texts))
        ordered = sorted(response.data, key=lambda item: item.index)
        return [list(item.embedding) for item in ordered]
