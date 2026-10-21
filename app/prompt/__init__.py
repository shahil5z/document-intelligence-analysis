"""Prompt files for grounded question answering (the assistant's "brain").

The text lives in this package as Markdown/JSON files so it can be read and reviewed
without touching code (see README.md). Files are read once per process and cached.

* ``system.md`` - system message;
* ``answer_instructions.md`` - output contract appended to the user message
  (``$source_count`` placeholder);
* ``response_schema.json`` - JSON schema for OpenAI structured outputs;
* ``insufficient_evidence.md`` - user-facing answer when no grounded answer is produced.

``<!-- ... -->`` comments are removed before the text is used. Bump ``PROMPT_VERSION``
whenever a file changes; it is logged and returned with every answer.
"""

import json
import re
from functools import cache, lru_cache
from importlib import resources
from string import Template
from typing import Any

PROMPT_VERSION = "2026-10-21.1"

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_FILES = frozenset(
    {"system.md", "answer_instructions.md", "insufficient_evidence.md", "response_schema.json"}
)


@cache
def load_prompt(name: str) -> str:
    """Return the text of ``name`` without HTML comments and surrounding blank lines."""
    if name not in _FILES:
        raise KeyError(f"unknown prompt file: {name}")
    raw = resources.files(__name__).joinpath(name).read_text(encoding="utf-8")
    text = _COMMENT.sub("", raw).strip()
    if not text:
        raise ValueError(f"prompt file {name} is empty")
    return text


def system_prompt() -> str:
    return load_prompt("system.md")


def answer_instructions(source_count: int) -> str:
    # substitute (not safe_substitute): a typo in a placeholder must fail loudly in tests.
    return Template(load_prompt("answer_instructions.md")).substitute(source_count=source_count)


def insufficient_evidence_answer() -> str:
    return load_prompt("insufficient_evidence.md")


@lru_cache(maxsize=1)
def response_schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(load_prompt("response_schema.json"))
    return schema
