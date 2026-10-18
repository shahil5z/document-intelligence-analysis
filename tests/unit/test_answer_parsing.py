"""answer_parsing: marker normalisation and reply shapes not covered by the replay set."""

import pytest

from app.services.answer_parsing import markers_in, normalize_markers, parse_reply


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a [1] b", "a [1] b"),
        ("a [1, 2] b", "a [1][2] b"),
        ("a [1;3]", "a [1][3]"),
        ("a [1-3]", "a [1][2][3]"),
        ("a [S1][S2]", "a [1][2]"),
        ("a [Source 2]", "a [2]"),
        ("a [source: 4]", "a [4]"),
        ("a [^5]", "a [5]"),
        ("a \u30101\u3011", "a [1]"),
        ("a (Source 3)", "a [3]"),
        ("a (Sources 1, 2)", "a [1][2]"),
        ("(1) a list item", "(1) a list item"),
        ("in [2024]", "in [2024]"),
        ("[link](https://x.test)", "[link](https://x.test)"),
    ],
)
def test_normalize_markers(raw: str, expected: str) -> None:
    assert normalize_markers(raw) == expected


def test_markers_in_order_of_first_appearance() -> None:
    assert markers_in("x [2] y [1] z [2]") == [2, 1]


def test_invalid_json_falls_back_to_text() -> None:
    reply = parse_reply('{"status": "answered", "answer": "unterminated [1]')
    assert reply.mode == "text"
    assert reply.status == "answered"


def test_json_without_known_fields_is_treated_as_text() -> None:
    reply = parse_reply('{"foo": "bar"} and the refund window is 30 days [1].')
    assert reply.mode == "text"
    assert "[1]" in reply.answer


def test_status_aliases_and_dict_citations() -> None:
    reply = parse_reply(
        '{"status": "Partially answered", "answer": "x [1]", '
        '"citations": [{"id": 1}, {"source": "S2"}], "missing": "y"}'
    )
    assert reply.status == "partial"
    assert reply.declared_citations == (1, 2)
    assert reply.missing_information == "y"
