"""Document data access. Every read/write is scoped by ``owner_id``.

Ownership is enforced here, in the query itself, so a document belonging to another
user is indistinguishable from a missing one (callers turn ``None`` into 404).
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Document


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_owner(self, document_id: uuid.UUID, owner_id: uuid.UUID) -> Document | None:
        return self._session.scalar(
            select(Document).where(Document.id == document_id, Document.owner_id == owner_id)
        )

    def get_by_checksum_for_owner(self, checksum: str, owner_id: uuid.UUID) -> Document | None:
        return self._session.scalar(
            select(Document).where(
                Document.owner_id == owner_id, Document.checksum_sha256 == checksum
            )
        )

    def list_for_owner(
        self, owner_id: uuid.UUID, *, offset: int, limit: int
    ) -> tuple[Sequence[Document], int]:
        total = (
            self._session.scalar(
                select(func.count()).select_from(Document).where(Document.owner_id == owner_id)
            )
            or 0
        )
        rows = self._session.scalars(
            select(Document)
            .where(Document.owner_id == owner_id)
            .order_by(Document.created_at.desc(), Document.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return rows, total

    def add(self, document: Document) -> Document:
        self._session.add(document)
        self._session.flush()
        return document

    def delete(self, document: Document) -> None:
        self._session.delete(document)
        self._session.flush()

    def get_unscoped(self, document_id: uuid.UUID) -> Document | None:
        """Owner-agnostic lookup for trusted internal callers (the worker) only."""
        return self._session.get(Document, document_id)
