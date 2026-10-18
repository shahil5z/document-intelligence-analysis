"""Deterministic test doubles for the AI providers (no network, no model downloads)."""

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.ai.base import ChatMessage
from app.ai.errors import LLMError
from app.db.models.document_chunk import EMBEDDING_DIMENSION

_WORD = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "my",
        "of",
        "on",
        "or",
        "the",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
    ]
)


def _terms(text: str) -> list[str]:
    terms = []
    for word in _WORD.findall(text.lower()):
        if word in _STOP_WORDS:
            continue
        # Crude plural folding so "refunds" and "refund" share a bucket.
        terms.append(word[:-1] if len(word) > 3 and word.endswith("s") else word)
    return terms


class HashingEmbeddingProvider:
    """Bag-of-words feature hashing into ``dimension`` buckets, L2-normalised.

    Texts sharing words get positive cosine similarity; texts without shared words get
    0 (unless two words collide in a bucket). md5 keeps it stable across processes.
    """

    def __init__(self, dimension: int = EMBEDDING_DIMENSION, *, fail: bool = False) -> None:
        self._dimension = dimension
        self.fail = fail
        self.calls: list[int] = []

    @property
    def model_name(self) -> str:
        return "test-hashing-embedder"

    @property
    def dimension(self) -> int:
        return self._dimension

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        for term in _terms(text):
            bucket = int(hashlib.md5(term.encode(), usedforsecurity=False).hexdigest(), 16)
            vector[bucket % self._dimension] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self.fail:
            from app.ai.errors import EmbeddingError  # noqa: PLC0415

            raise EmbeddingError("embedding inference failed")
        self.calls.append(len(texts))
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


@dataclass
class MockLLM:
    """Records prompts; returns ``response`` (``{labels}`` is replaced by the source ids)."""

    response: str = "The answer is supported by the documents [S1]."
    error: bool = False
    calls: list[list[ChatMessage]] = field(default_factory=list)

    @property
    def model_name(self) -> str:
        return "mock-llm"

    def complete(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(list(messages))
        if self.error:
            raise LLMError("the language model did not respond in time")
        return self.response


@dataclass
class ReverseReranker:
    """Scores passages by length (longest first), to make reordering observable."""

    calls: int = 0

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        del query
        self.calls += 1
        return [float(len(passage)) for passage in passages]
