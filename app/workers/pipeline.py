"""Processing pipeline extension point.

The worker calls ``DocumentPipeline.run`` while the job is in ``processing``. Today the
only step verifies that the stored bytes still match the size and SHA-256 recorded at
upload time. Text extraction, chunking and embeddings (DIP2) are added as further steps.
"""

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.storage.base import StorageService


class PermanentProcessingError(Exception):
    """A failure that retrying will not fix. ``safe_message`` is shown to the user."""

    def __init__(self, safe_message: str) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message


class TransientProcessingError(Exception):
    """A failure worth retrying (e.g. a temporarily unavailable dependency)."""


@dataclass(frozen=True)
class PipelineContext:
    document_id: uuid.UUID
    owner_id: uuid.UUID
    storage_key: str
    content_type: str
    file_size: int
    checksum_sha256: str
    storage: StorageService


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

    def run(self, context: PipelineContext) -> None:
        for step in self._steps:
            step.run(context)


def build_default_pipeline() -> DocumentPipeline:
    return DocumentPipeline([IntegrityCheckStep()])
