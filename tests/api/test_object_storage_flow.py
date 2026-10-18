"""End-to-end API flow with the S3 storage backend (moto in-process S3)."""

from collections.abc import Iterator

import boto3
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from moto import mock_aws

from app.api.dependencies.services import get_storage
from app.storage.base import StorageError
from app.storage.local import LocalStorage
from app.storage.s3 import S3Storage
from tests.conftest import RecordingDispatcher, upload_and_index
from tests.fakes import HashingEmbeddingProvider

BUCKET = "dip-flow"


@pytest.fixture
def s3_storage(app: FastAPI) -> Iterator[S3Storage]:
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        storage = S3Storage(
            bucket=BUCKET,
            access_key_id="testing",
            secret_access_key="testing",
            prefix="dip",
        )
        app.dependency_overrides[get_storage] = lambda: storage
        yield storage


def test_upload_index_search_and_delete_with_object_storage(
    client: TestClient,
    user_headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    embedder: HashingEmbeddingProvider,
    s3_storage: S3Storage,
) -> None:
    text = "Customers may return unused items within 30 days of delivery."
    document_id, outcome = upload_and_index(
        client,
        user_headers,
        dispatcher,
        s3_storage,
        embedder,
        ("policy.txt", text.encode(), "text/plain"),
    )
    assert outcome.value == "completed"
    keys = [
        item["Key"]
        for item in boto3.client("s3", region_name="us-east-1").list_objects_v2(Bucket=BUCKET)[
            "Contents"
        ]
    ]
    assert len(keys) == 1
    assert keys[0].startswith("dip/documents/")

    results = client.post(
        "/search", json={"query": "return unused items", "mode": "keyword"}, headers=user_headers
    ).json()["results"]
    assert results[0]["document_id"] == str(document_id)
    assert "30 days" in results[0]["text"]

    assert client.delete(f"/documents/{document_id}", headers=user_headers).status_code == 204
    listing = boto3.client("s3", region_name="us-east-1").list_objects_v2(Bucket=BUCKET)
    assert listing.get("KeyCount", 0) == 0


def test_storage_outage_during_upload_returns_503(
    client: TestClient,
    user_headers: dict[str, str],
    storage: LocalStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*_args: object, **_kwargs: object) -> int:
        raise StorageError("bucket unreachable")

    monkeypatch.setattr(storage, "save", unavailable)
    response = client.post(
        "/documents", files={"file": ("a.txt", b"hello", "text/plain")}, headers=user_headers
    )
    assert response.status_code == 503
    assert response.json()["error"]["message"] == "File storage is temporarily unavailable"
    listed = client.get("/documents", headers=user_headers).json()
    assert listed["total"] == 0
