"""Integration tests need the real PostgreSQL test database (skipped without one)."""

import pytest


@pytest.fixture(autouse=True)
def _requires_database(database: None) -> None:
    del database
