from collections.abc import Sequence
from typing import Literal, Protocol, TypedDict


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMProvider(Protocol):
    """Generates text from a list of chat messages."""

    def complete(self, messages: Sequence[ChatMessage]) -> str: ...


class EmbeddingProvider(Protocol):
    """Turns texts into embedding vectors (one vector per input, same order)."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
