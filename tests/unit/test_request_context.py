import uuid

import pytest

from app.core.request_context import sanitize_request_id


def test_valid_request_ids_are_kept() -> None:
    value = str(uuid.uuid4())
    assert sanitize_request_id(value) == value
    assert sanitize_request_id("abc-1234") == "abc-1234"


@pytest.mark.parametrize(
    "value", [None, "", "short", "has space in it", "x" * 65, "inject\nnewline", "<script>"]
)
def test_unsafe_request_ids_are_replaced(value: str | None) -> None:
    result = sanitize_request_id(value)
    assert result != value
    uuid.UUID(result)
