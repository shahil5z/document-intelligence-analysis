"""Processing pipeline extension point.

The worker calls ``DocumentPipeline.run`` while the job is in ``processing``. The first
step verifies that the stored bytes still match the size and SHA-256 recorded at upload
time. DIP2 adds extract -> normalize -> chunk -> embed -> index (``app/workers/steps.py``,
assembled by ``build_indexing_pipeline``); intermediate results live in
``PipelineContext.state``.
"""

import hashlib
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from app.core.metrics import STAGE_DURATION
from app.storage.base import StorageService

if TYPE_CHECKING:
    from app.processing.chunking import TextChunk
    from app.processing.content import DocumentContent


class PermanentProcessingError(Exception):
    """A failure that retrying will not fix. ``safe_message`` is shown to the user."""

    def __init__(self, safe_message: str) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message


class TransientProcessingError(Exception):
    """A failure worth retrying (e.g. a temporarily unavailable dependency)."""


@dataclass
class PipelineState:
    """Mutable hand-over between steps of one attempt (never persisted as a whole)."""

    content: "DocumentContent | None" = None
    chunks: "list[TextChunk]" = field(default_factory=list)
    embeddings: list[list[float]] = field(default_factory=list)


@dataclass(frozen=True)
class PipelineContext:
    document_id: uuid.UUID
    owner_id: uuid.UUID
    storage_key: str
    content_type: str
    file_size: int
    checksum_sha256: str
    storage: StorageService
    state: PipelineState = field(default_factory=PipelineState)


class PipelineStep(Protocol):
    name: str

    def run(self, context: PipelineContext) -> None: ...


class IntegrityCheckStep:
    name = "integrity_check"

    def run(self, context: PipelineContext) -> None:
        if not context.storage.exists(context.storage_key):
            raise PermanentProcessingError("The stored file could not be found")
        sha256 = hashlib.sha256()
        size = 0
        for chunk in context.storage.iter_chunks(context.storage_key):
            sha256.update(chunk)
            size += len(chunk)
        if size != context.file_size or sha256.hexdigest() != context.checksum_sha256:
            raise PermanentProcessingError("The stored file failed integrity verification")


class DocumentPipeline:
    def __init__(self, steps: Sequence[PipelineStep]) -> None:
        self._steps = tuple(steps)

    @property
    def step_names(self) -> tuple[str, ...]:
        return tuple(step.name for step in self._steps)

    def run(self, context: PipelineContext, on_step: Callable[[str], None] | None = None) -> None:
        for step in self._steps:
            if on_step is not None:
                on_step(step.name)
            started = time.perf_counter()
            try:
                step.run(context)
            finally:
                STAGE_DURATION.labels(step.name).observe(time.perf_counter() - started)


def build_default_pipeline() -> DocumentPipeline:
    """Integrity check only (the DIP1 pipeline). The worker uses ``build_indexing_pipeline``
    from ``app.workers.steps``, which starts with this same step."""
    return DocumentPipeline([IntegrityCheckStep()])
