# ADR-004: Storage abstraction with a local filesystem backend

**Status:** Accepted (DIP1)

## Context
Uploaded files must be stored durably and read by the worker. Local development uses
a disk volume; a deployed system would likely use object storage.

## Decision
- `StorageService` ABC (`app/storage/base.py`): `save(key, chunks)`, `iter_chunks(key)`,
  `delete(key)`, `exists(key)`. Callers only handle opaque keys.
- `LocalStorage` (`app/storage/local.py`) writes to a temp file in the target directory,
  fsyncs, then atomically renames. Keys must match a strict grammar **and** the resolved
  path must stay inside the root (guards `..`, absolute paths and symlink escapes).
- Keys are generated server side: `documents/<owner_id>/<document_uuid_hex>.<ext>`. The
  user-supplied filename is sanitised and stored for display only.
- Storage keys and paths are never returned by the API.

## Alternatives
- **Store bytes in PostgreSQL** (`bytea`/large objects): simple consistency, but bloats
  the database and backups.
- **Implement S3 now**: no cloud target exists in DIP1; an untested adapter would be
  misleading. An `S3Storage` can implement the same interface later.

## Consequences
- API and worker must share the storage root (a named volume in docker compose).
- Database and file system are not one transaction. Order on upload: write file ->
  commit row (file removed if commit fails). On delete: commit row removal -> delete file
  (a failure leaves an orphan file, logged, never a dangling record).
