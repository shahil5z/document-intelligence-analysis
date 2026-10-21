"""strip_citation_markers: removes [n] citation markers only, never other Markdown."""

import pytest

from app.services.answer_format import strip_citation_markers


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("Refunds take 14 days [1].", "Refunds take 14 days."),
        ("A [1][2], B [3, 4]; C[5]", "A, B; C"),
        ("Fees apply [2][3] and more [1]", "Fees apply and more"),
        ("Done [1] .", "Done."),
        ("1. First [1]\n2. Second [2]", "1. First\n2. Second"),
        ("- item [4]\n- other", "- item\n- other"),
        ("| GPU | W |\n|---|---|\n| A [1] | 300 [2] |", "| GPU | W |\n|---|---|\n| A | 300 |"),
        ("**Bold** [1] text", "**Bold** text"),
    ],
)
def test_markers_are_removed_with_their_spacing(raw: str, clean: str) -> None:
    assert strip_citation_markers(raw) == clean


@pytest.mark.parametrize(
    "text",
    [
        "See [docs](https://example.com/a) and [1](https://example.com/b).",
        "Reference style [text][1].\n\n[1]: https://example.com",
        "![chart][2]",
        "Escaped \\[1] stays.",
        "Year [2026] and [101] are not citations.",
        "1. Numbered\n2. List",
        "[ ] task and [x] done",
    ],
)
def test_other_markdown_is_untouched(text: str) -> None:
    assert strip_citation_markers(text) == text


def test_code_blocks_and_inline_code_are_untouched() -> None:
    raw = "Intro [1].\n\n```python\nx = arr[1]  # [2]\n```\n\nUse `items[3]` here [4]."
    assert strip_citation_markers(raw) == (
        "Intro.\n\n```python\nx = arr[1]  # [2]\n```\n\nUse `items[3]` here."
    )


def test_tilde_fence_and_blank_result() -> None:
    assert strip_citation_markers("~~~\n[1]\n~~~") == "~~~\n[1]\n~~~"
    assert strip_citation_markers("[1]") == ""
