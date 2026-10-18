"""Conservative text normalization applied per page before chunking.

Goals: stable whitespace and Unicode form for chunking, embedding and full-text search,
without rewriting content. Paragraph breaks (blank lines) are preserved; single line
breaks are kept because they often carry structure (lists, addresses, tables).
"""

import re
import unicodedata
from dataclasses import replace

from app.processing.content import DocumentContent, PageText

# Zero-width and formatting characters that only disturb tokenization and search.
_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff"), None)
# Unicode spaces (NBSP, thin space, ...) become a plain space.
_SPACES = dict.fromkeys(
    map(
        ord,
        "\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006"
        "\u2007\u2008\u2009\u200a\u202f\u205f\u3000",
    ),
    " ",
)
# C0/C1 control characters except tab and newline.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_HORIZONTAL_WS = re.compile(r"[ \t\f\v]+")
_TRAILING_WS = re.compile(r"[ \t]+\n")
_LEADING_WS = re.compile(r"\n[ \t]+")
_MANY_BLANK_LINES = re.compile(r"\n{3,}")
# "exam-\nple" -> "example" only between lower-case letters (line-break hyphenation).
_HYPHENATED_BREAK = re.compile(r"(?<=[a-z])-\n(?=[a-z])")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_INVISIBLE).translate(_SPACES)
    text = _CONTROL.sub("", text)
    text = _HORIZONTAL_WS.sub(" ", text)
    text = _TRAILING_WS.sub("\n", text)
    text = _LEADING_WS.sub("\n", text)
    text = _HYPHENATED_BREAK.sub("", text)
    text = _MANY_BLANK_LINES.sub("\n\n", text)
    return text.strip()


def normalize_content(content: DocumentContent) -> DocumentContent:
    pages = tuple(
        PageText(number=page.number, text=normalize_text(page.text)) for page in content.pages
    )
    return replace(content, pages=pages)
