from collections.abc import Sequence
from typing import Literal, Protocol, TypedDict


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMProvider(Protocol):
    """Generates text from a list of chat messages."""

    @property
    def model_name(self) -> str: ...

    def complete(self, messages: Sequence[ChatMessage]) -> str: ...


class EmbeddingProvider(Protocol):
    """Turns texts into embedding vectors (one vector per input, same order).

    ``embed`` is for document passages, ``embed_query`` for search queries (some models
    use an instruction prefix for queries only). ``dimension`` is the vector size.
    """

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class Reranker(Protocol):
    """Scores (query, passage) pairs; higher means more relevant."""

    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...
