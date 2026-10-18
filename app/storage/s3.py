"""S3-compatible object storage (AWS S3, MinIO, OCI Object Storage compatibility API).

Keys follow the same grammar as ``LocalStorage`` and are stored under an optional
prefix. Uploads are spooled locally first and sent with a single managed upload once
the whole stream has been read, so an upload that is aborted mid-stream (size limit,
client disconnect) never leaves a partial object behind, and the object appears
atomically. boto3 is imported lazily so the API and worker start without it when the
local backend is used.
"""

import tempfile
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, Any, Literal

from app.storage.base import StorageError, StorageKeyError, StorageService
from app.storage.local import KEY_PATTERN

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

_SPOOL_IN_MEMORY_BYTES = 8 * 1024 * 1024
_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}


class S3Storage(StorageService):
    def __init__(
        self,
        *,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        endpoint_url: str | None = None,
        region: str = "us-east-1",
        prefix: str = "",
        addressing_style: Literal["path", "virtual", "auto"] = "path",
        client: "S3Client | None" = None,
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        if client is None:
            import boto3  # noqa: PLC0415  (lazy: only needed for this backend)
            from botocore.config import Config  # noqa: PLC0415

            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                region_name=region,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                config=Config(
                    s3={"addressing_style": addressing_style},
                    signature_version="s3v4",
                    retries={"max_attempts": 3, "mode": "standard"},
                    connect_timeout=5,
                    read_timeout=60,
                    # Newer botocore adds CRC checksums to every request by default; some
                    # S3-compatible services (including OCI) reject them, so only send
                    # checksums when an operation requires one.
                    request_checksum_calculation="when_required",
                    response_checksum_validation="when_required",
                ),
            )
        self._client = client

    def _object_key(self, key: str) -> str:
        if not KEY_PATTERN.fullmatch(key) or ".." in key.split("/"):
            raise StorageKeyError("Invalid storage key")
        return f"{self._prefix}/{key}" if self._prefix else key

    def save(self, key: str, chunks: Iterable[bytes]) -> int:
        object_key = self._object_key(key)
        written = 0
        with tempfile.SpooledTemporaryFile(max_size=_SPOOL_IN_MEMORY_BYTES) as spool:
            # Reading the whole stream first: if it raises (e.g. upload too large), the
            # exception propagates before anything reaches the bucket.
            for chunk in chunks:
                spool.write(chunk)
                written += len(chunk)
            spool.seek(0)
            try:
                self._client.upload_fileobj(spool, self._bucket, object_key)
            except Exception as exc:
                raise StorageError("Object storage upload failed") from exc
        return written

    def iter_chunks(self, key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        object_key = self._object_key(key)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=object_key)
        except Exception as exc:
            if _is_not_found(exc):
                raise FileNotFoundError(key) from exc
            raise StorageError("Object storage read failed") from exc
        body = response["Body"]
        try:
            yield from body.iter_chunks(chunk_size)
        finally:
            body.close()

    def delete(self, key: str) -> bool:
        object_key = self._object_key(key)
        if not self.exists(key):
            return False
        try:
            self._client.delete_object(Bucket=self._bucket, Key=object_key)
        except Exception as exc:
            raise StorageError("Object storage delete failed") from exc
        return True

    def exists(self, key: str) -> bool:
        object_key = self._object_key(key)
        try:
            self._client.head_object(Bucket=self._bucket, Key=object_key)
        except Exception as exc:
            if _is_not_found(exc):
                return False
            raise StorageError("Object storage lookup failed") from exc
        return True

    def check(self) -> None:
        """Raise ``StorageError`` if the bucket is unreachable (readiness/diagnostics)."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception as exc:
            raise StorageError("Object storage bucket is not reachable") from exc


def _is_not_found(exc: Exception) -> bool:
    response: Any = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    code = str(response.get("Error", {}).get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in _NOT_FOUND_CODES or status == 404
