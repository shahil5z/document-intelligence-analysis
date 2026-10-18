"""Optional cross-encoder reranker (RERANKING_ENABLED=false by default)."""

import threading
from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.ai.errors import EmbeddingError

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder


class CrossEncoderReranker:
    def __init__(self, model_name: str, *, device: str = "cpu", num_threads: int = 0) -> None:
        self._num_threads = num_threads
        self._model_name = model_name
        self._device = device
        self._model: CrossEncoder | None = None
        self._lock = threading.Lock()

    def _load(self) -> "CrossEncoder":
        with self._lock:
            if self._model is None:
                from sentence_transformers import CrossEncoder  # noqa: PLC0415

                from app.ai.embeddings import apply_torch_threads  # noqa: PLC0415

                apply_torch_threads(self._num_threads)

                self._model = CrossEncoder(self._model_name, device=self._device)
        return self._model

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        try:
            scores = self._load().predict([(query, passage) for passage in passages])
        except (RuntimeError, ValueError) as exc:
            raise EmbeddingError("reranking failed") from exc
        return [float(value) for value in scores]
