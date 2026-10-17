import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, Document, DocumentProcessingJob
from app.storage.local import LocalStorage
from tests.conftest import RecordingDispatcher
from tests.factories import DOCX_CONTENT_TYPE, pdf_file, text_file


def upload(client: TestClient, headers: dict[str, str], file: tuple[str, bytes, str]) -> Any:
    return client.post("/documents", files={"file": file}, headers=headers)


def test_upload_pdf_creates_document_and_queues_job(
    client: TestClient,
    user_headers: dict[str, str],
    db_session: Session,
    storage: LocalStorage,
    dispatcher: RecordingDispatcher,
) -> None:
    response = upload(client, user_headers, pdf_file())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["job_status"] == "queued"

    document = db_session.get(Document, uuid.UUID(body["id"]))
    assert document is not None
    assert document.original_filename == "report.pdf"
    assert document.filename == f"{document.id.hex}.pdf"
    assert len(document.checksum_sha256) == 64
    assert storage.exists(document.storage_key)

    job = db_session.get(DocumentProcessingJob, uuid.UUID(body["job_id"]))
    assert job is not None
    assert job.task_id is not None
    assert dispatcher.calls == [
        {"document_id": document.id, "job_id": job.id, "task_id": job.task_id}
    ]
    assert "document.uploaded" in db_session.scalars(select(AuditLog.action)).all()


def test_upload_response_never_exposes_storage_details(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    doc_id = upload(client, user_headers, text_file()).json()["id"]
    detail = client.get(f"/documents/{doc_id}", headers=user_headers).json()
    assert "storage_key" not in detail
    assert "filename" not in detail
    assert "documents/" not in str(detail)


def test_upload_txt_and_docx(client: TestClient, user_headers: dict[str, str]) -> None:
    assert upload(client, user_headers, text_file()).status_code == 201
    docx = ("letter.docx", b"PK\x03\x04" + b"\x00" * 64, DOCX_CONTENT_TYPE)
    assert upload(client, user_headers, docx).status_code == 201


def test_upload_requires_authentication(client: TestClient) -> None:
    assert client.post("/documents", files={"file": text_file()}).status_code == 401


def test_upload_rejects_disallowed_extension(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    response = upload(client, user_headers, ("run.exe", b"MZ\x90\x00", "application/octet-stream"))
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_upload_rejects_mismatched_magic_bytes(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    response = upload(client, user_headers, ("fake.pdf", b"this is not a pdf", "application/pdf"))
    assert response.status_code == 415


def test_upload_rejects_oversized_file_and_cleans_up(
    client: TestClient, user_headers: dict[str, str], storage: LocalStorage, db_session: Session
) -> None:
    too_big = text_file("x" * (64 * 1024 + 1))
    response = upload(client, user_headers, too_big)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert db_session.scalar(select(Document)) is None
    stored = [p for p in storage._root.rglob("*") if p.is_file()]  # noqa: SLF001
    assert stored == []


def test_upload_rejects_empty_file(client: TestClient, user_headers: dict[str, str]) -> None:
    assert upload(client, user_headers, ("empty.txt", b"", "text/plain")).status_code == 400


def test_duplicate_upload_for_same_user_returns_409(
    client: TestClient, user_headers: dict[str, str], other_user_headers: dict[str, str]
) -> None:
    assert upload(client, user_headers, pdf_file()).status_code == 201
    duplicate = upload(client, user_headers, pdf_file(name="renamed.pdf"))
    assert duplicate.status_code == 409
    # The same content is allowed for a different user.
    assert upload(client, other_user_headers, pdf_file()).status_code == 201


def test_enqueue_failure_marks_job_failed(
    client: TestClient, user_headers: dict[str, str], dispatcher: RecordingDispatcher
) -> None:
    dispatcher.fail = True
    response = upload(client, user_headers, text_file())
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["job_status"] == "failed"
    status = client.get(f"/documents/{response.json()['id']}/status", headers=user_headers).json()
    assert status["job"]["error_message"].startswith("Processing could not be scheduled")
    assert "broker" not in status["job"]["error_message"]


def test_list_pagination_and_page_size_cap(
    client: TestClient, user_headers: dict[str, str]
) -> None:
    for i in range(5):
        assert upload(client, user_headers, text_file(f"document number {i}")).status_code == 201

    first = client.get(
        "/documents", params={"page": 1, "page_size": 2}, headers=user_headers
    ).json()
    assert first["total"] == 5
    assert first["page"] == 1
    assert first["page_size"] == 2
    assert len(first["items"]) == 2
    last = client.get("/documents", params={"page": 3, "page_size": 2}, headers=user_headers).json()
    assert len(last["items"]) == 1
    all_ids = {
        item["id"]
        for page in (1, 2, 3)
        for item in client.get(
            "/documents", params={"page": page, "page_size": 2}, headers=user_headers
        ).json()["items"]
    }
    assert len(all_ids) == 5

    assert (
        client.get("/documents", params={"page_size": 101}, headers=user_headers).status_code == 422
    )
    assert client.get("/documents", params={"page": 0}, headers=user_headers).status_code == 422


def test_list_only_returns_own_documents(
    client: TestClient, user_headers: dict[str, str], other_user_headers: dict[str, str]
) -> None:
    upload(client, user_headers, text_file("alice"))
    upload(client, other_user_headers, text_file("bob"))
    body = client.get("/documents", headers=user_headers).json()
    assert body["total"] == 1


def test_get_document_detail(client: TestClient, user_headers: dict[str, str]) -> None:
    doc_id = upload(client, user_headers, pdf_file()).json()["id"]
    response = client.get(f"/documents/{doc_id}", headers=user_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == doc_id
    assert body["content_type"] == "application/pdf"
    assert body["original_filename"] == "report.pdf"


def test_other_users_document_returns_404(
    client: TestClient, user_headers: dict[str, str], other_user_headers: dict[str, str]
) -> None:
    doc_id = upload(client, user_headers, pdf_file()).json()["id"]
    for path in (f"/documents/{doc_id}", f"/documents/{doc_id}/status"):
        response = client.get(path, headers=other_user_headers)
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "Document not found"
    random_id = uuid.uuid4()
    assert client.get(f"/documents/{random_id}", headers=user_headers).status_code == 404


def test_delete_document_removes_record_and_file(
    client: TestClient, user_headers: dict[str, str], storage: LocalStorage, db_session: Session
) -> None:
    doc_id = upload(client, user_headers, pdf_file()).json()["id"]
    document = db_session.get(Document, uuid.UUID(doc_id))
    assert document is not None
    key = document.storage_key
    db_session.expunge_all()

    response = client.delete(f"/documents/{doc_id}", headers=user_headers)
    assert response.status_code == 204
    assert response.content == b""
    assert not storage.exists(key)
    assert db_session.get(Document, uuid.UUID(doc_id)) is None
    assert db_session.scalar(select(DocumentProcessingJob)) is None
    assert client.get(f"/documents/{doc_id}", headers=user_headers).status_code == 404
    assert "document.deleted" in db_session.scalars(select(AuditLog.action)).all()


def test_delete_other_users_document_returns_404(
    client: TestClient,
    user_headers: dict[str, str],
    other_user_headers: dict[str, str],
    storage: LocalStorage,
) -> None:
    doc_id = upload(client, user_headers, pdf_file()).json()["id"]
    assert client.delete(f"/documents/{doc_id}", headers=other_user_headers).status_code == 404
    assert client.get(f"/documents/{doc_id}", headers=user_headers).status_code == 200


def test_status_endpoint(client: TestClient, user_headers: dict[str, str]) -> None:
    upload_body = upload(client, user_headers, text_file()).json()
    response = client.get(f"/documents/{upload_body['id']}/status", headers=user_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == upload_body["id"]
    assert body["status"] == "queued"
    assert body["job"]["id"] == upload_body["job_id"]
    assert body["job"]["status"] == "queued"
    assert body["job"]["attempts"] == 0
    assert body["job"]["error_message"] is None
    assert "task_id" not in body["job"]
