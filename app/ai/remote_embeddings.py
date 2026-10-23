"""Embedding provider that delegates to the API's ``POST /internal/embed``.

Used by the Celery worker on small machines so that only the API process holds the
embedding model. The shared secret travels in the ``X-Internal-Secret`` header; the
endpoint is reachable only inside the compose network (Caddy answers 404).
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any

from app.ai.errors import EmbeddingError, EmbeddingServiceUnavailableError

SECRET_HEADER = "X-Internal-Secret"  # noqa: S105  (header name, not a secret)


class RemoteEmbeddingProvider:
    def __init__(
        self,
        url: str,
        secret: str,
        *,
        model_name: str,
        expected_dimension: int,
        batch_size: int = 8,
        timeout_seconds: float = 110.0,
        retries: int = 2,
    ) -> None:
        self._url = url
        self._secret = secret
        self._model_name = model_name
        self._expected_dimension = expected_dimension
        self._batch_size = batch_size
        self._timeout = timeout_seconds
        self._retries = retries

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._expected_dimension

    def _post(self, texts: Sequence[str], kind: str) -> list[list[float]]:
        body = json.dumps({"texts": list(texts), "kind": kind}).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310  (URL comes from configuration)
            self._url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", SECRET_HEADER: self._secret},
        )
        last: Exception | None = None
        payload: Any = None
        for attempt in range(self._retries + 1):
            if attempt:
                time.sleep(min(2.0 * attempt, 5.0))
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                    payload = json.loads(response.read())
                last = None
                break
            except urllib.error.HTTPError as exc:
                if exc.code < 500:
                    raise EmbeddingError(
                        f"embedding service rejected the request ({exc.code})"
                    ) from exc
                last = exc
            except TimeoutError as exc:
                # The API is still busy with this batch; sending it again only queues a
                # second copy behind the first on a CPU-bound process. Fail fast and let
                # the job-level retry try later.
                last = exc
                break
            except (urllib.error.URLError, ConnectionError) as exc:
                if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, TimeoutError):
                    last = exc
                    break
                last = exc
        if last is not None:
            raise EmbeddingServiceUnavailableError(
                f"embedding service unavailable ({type(last).__name__})"
            ) from last
        vectors = payload.get("vectors") if isinstance(payload, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbeddingError("embedding service returned the wrong number of vectors")
        if any(len(vector) != self._expected_dimension for vector in vectors):
            raise EmbeddingError("embedding service returned a vector of the wrong size")
        return [[float(value) for value in vector] for vector in vectors]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), self._batch_size):
            vectors.extend(self._post(texts[offset : offset + self._batch_size], "passage"))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._post([text], "query")[0]
