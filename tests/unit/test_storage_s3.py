"""S3Storage contract tests.

Always run against moto's in-process S3. When ``TEST_S3_ENDPOINT_URL``,
``TEST_S3_ACCESS_KEY_ID``, ``TEST_S3_SECRET_ACCESS_KEY`` and ``TEST_S3_BUCKET`` are set
(e.g. a local MinIO container), the same tests also run against that real
S3-compatible server.
"""

import os
import uuid
from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws
from pydantic import SecretStr

from app.core.config import Settings, SettingsError, load_settings
from app.storage.base import StorageError, StorageKeyError
from app.storage.factory import build_storage_service
from app.storage.s3 import S3Storage

_MOTO_BUCKET = "dip-test-bucket"


def _real_server_config() -> dict[str, str] | None:
    names = {
        "endpoint_url": "TEST_S3_ENDPOINT_URL",
        "access_key_id": "TEST_S3_ACCESS_KEY_ID",
        "secret_access_key": "TEST_S3_SECRET_ACCESS_KEY",
        "bucket": "TEST_S3_BUCKET",
    }
    values = {key: os.environ.get(env, "") for key, env in names.items()}
    return values if all(values.values()) else None


@pytest.fixture(params=["moto", "server"])
def s3_storage(request: pytest.FixtureRequest) -> Iterator[S3Storage]:
    prefix = f"test-{uuid.uuid4().hex[:8]}"
    if request.param == "moto":
        with mock_aws():
            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=_MOTO_BUCKET)
            yield S3Storage(
                bucket=_MOTO_BUCKET,
                access_key_id="testing",
                secret_access_key="testing",
                prefix=prefix,
            )
        return
    config = _real_server_config()
    if config is None:
        pytest.skip("TEST_S3_* not set (no S3-compatible server for this run)")
    yield S3Storage(
        bucket=config["bucket"],
        access_key_id=config["access_key_id"],
        secret_access_key=config["secret_access_key"],
        endpoint_url=config["endpoint_url"],
        prefix=prefix,
    )


def _chunks(*parts: bytes) -> Iterator[bytes]:
    yield from parts


def test_save_read_exists_delete_round_trip(s3_storage: S3Storage) -> None:
    key = "documents/user/abc.pdf"
    assert s3_storage.exists(key) is False
    assert s3_storage.save(key, _chunks(b"hello ", b"world")) == 11
    assert s3_storage.exists(key) is True
    assert b"".join(s3_storage.iter_chunks(key, chunk_size=4)) == b"hello world"
    assert s3_storage.delete(key) is True
    assert s3_storage.exists(key) is False
    assert s3_storage.delete(key) is False


def test_large_object_streams_in_chunks(s3_storage: S3Storage) -> None:
    payload = os.urandom(9 * 1024 * 1024 + 17)  # above the in-memory spool size
    key = "documents/user/big.bin"
    s3_storage.save(key, (payload[i : i + 65536] for i in range(0, len(payload), 65536)))
    chunks = list(s3_storage.iter_chunks(key, chunk_size=1024 * 1024))
    assert len(chunks) > 1
    assert b"".join(chunks) == payload
    s3_storage.delete(key)


def test_failed_stream_leaves_no_object(s3_storage: S3Storage) -> None:
    def exploding() -> Iterator[bytes]:
        yield b"partial data"
        raise ValueError("upload too large")

    key = "documents/user/aborted.txt"
    with pytest.raises(ValueError, match="too large"):
        s3_storage.save(key, exploding())
    assert s3_storage.exists(key) is False


def test_missing_object_raises_file_not_found(s3_storage: S3Storage) -> None:
    with pytest.raises(FileNotFoundError):
        list(s3_storage.iter_chunks("documents/user/missing.txt"))


@pytest.mark.parametrize(
    "key", ["../escape", "/absolute", "documents/../x", "", "a//b", "documents/.hidden"]
)
def test_invalid_keys_are_rejected(s3_storage: S3Storage, key: str) -> None:
    with pytest.raises(StorageKeyError):
        s3_storage.exists(key)


def test_bucket_check(s3_storage: S3Storage) -> None:
    s3_storage.check()


def test_prefix_is_applied_to_object_keys() -> None:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=_MOTO_BUCKET)
        storage = S3Storage(
            bucket=_MOTO_BUCKET,
            access_key_id="testing",
            secret_access_key="testing",
            prefix="/tenant-a/",
        )
        storage.save("documents/u/f.txt", _chunks(b"x"))
        keys = [item["Key"] for item in client.list_objects_v2(Bucket=_MOTO_BUCKET)["Contents"]]
        assert keys == ["tenant-a/documents/u/f.txt"]


def test_unreachable_endpoint_raises_storage_error() -> None:
    storage = S3Storage(
        bucket="nope",
        access_key_id="x",
        secret_access_key="x",
        endpoint_url="http://127.0.0.1:1",
    )
    with pytest.raises(StorageError):
        storage.exists("documents/u/f.txt")
    with pytest.raises(StorageError):
        storage.save("documents/u/f.txt", _chunks(b"x"))


def _settings(**overrides: object) -> Settings:
    return load_settings(_env_file=None, app_env="test", jwt_secret_key="k" * 40, **overrides)


def test_factory_builds_s3_storage_for_s3_and_oci() -> None:
    common = {
        "storage_s3_bucket": "b",
        "storage_s3_access_key_id": SecretStr("id"),
        "storage_s3_secret_access_key": SecretStr("secret"),
    }
    assert isinstance(build_storage_service(_settings(storage_backend="s3", **common)), S3Storage)
    oci = _settings(
        storage_backend="oci",
        storage_s3_endpoint_url="https://ns.compat.objectstorage.eu-frankfurt-1.oraclecloud.com",
        storage_s3_region="eu-frankfurt-1",
        **common,
    )
    assert isinstance(build_storage_service(oci), S3Storage)


def test_object_storage_settings_are_validated() -> None:
    with pytest.raises(SettingsError, match="STORAGE_S3_BUCKET is required") as info:
        _settings(storage_backend="oci")
    message = str(info.value)
    assert "STORAGE_S3_ENDPOINT_URL is required when STORAGE_BACKEND=oci" in message
    assert "STORAGE_S3_SECRET_ACCESS_KEY is required" in message
    with pytest.raises(SettingsError, match="STORAGE_S3_PREFIX must be a relative key prefix"):
        _settings(
            storage_backend="s3",
            storage_s3_bucket="b",
            storage_s3_access_key_id=SecretStr("id"),
            storage_s3_secret_access_key=SecretStr("secret"),
            storage_s3_prefix="../x",
        )
