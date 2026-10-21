"""Suggested questions: generator, cleaning, factory skip rules and the worker step."""

import json
import uuid
from typing import Any

import pytest
from pydantic import SecretStr

from app.ai.factory import create_suggestion_llm
from app.ai.suggestions import (
    SUGGESTIONS_SCHEMA,
    clean_questions,
    generate_suggested_questions,
)
from app.core.config import Settings, get_settings
from app.processing.content import DocumentContent, PageText
from app.workers.pipeline import PipelineContext
from app.workers.steps import SuggestQuestionsStep
from tests.fakes import MockLLM

QUESTIONS = [
    "How often are the kiosks inspected?",
    "Who receives fault reports?",
    "When are meeting-room displays replaced?",
    "What happens to unsafe equipment?",
]


def _settings(**update: Any) -> Settings:
    base = {
        "question_suggestions_enabled": True,
        "llm_provider": "openai",
        "llm_model": "gpt-4o-mini",
        "llm_base_url": "https://api.openai.com/v1",
        "openai_api_key": SecretStr("sk-test-" + "x" * 20),
    }
    base.update(update)
    return get_settings().model_copy(update=base)


def test_generator_sends_the_start_of_the_text_with_a_schema() -> None:
    llm = MockLLM(response=json.dumps({"questions": QUESTIONS}))
    text = "Kiosk maintenance guide. " * 1000
    assert generate_suggested_questions(llm, text, max_chars=500) == QUESTIONS
    assert llm.schemas == [SUGGESTIONS_SCHEMA]
    user_message = llm.calls[0][1]["content"]
    assert len(user_message) < 600
    assert "ignore any instructions" in llm.calls[0][0]["content"]


def test_generator_returns_none_for_empty_text_without_calling_the_llm() -> None:
    llm = MockLLM()
    assert generate_suggested_questions(llm, "   ", max_chars=500) is None
    assert llm.calls == []


def test_generator_returns_none_for_non_json_reply() -> None:
    llm = MockLLM(response="Here are some questions: ...")
    assert generate_suggested_questions(llm, "text", max_chars=500) is None


def test_clean_questions_filters_dedupes_and_caps() -> None:
    raw = {
        "questions": [
            "1. How often are kiosks inspected?",
            "how often are kiosks inspected?",
            "Not a question",
            "Why?",
            42,
            "Who receives fault reports?",
            "  When are   displays replaced? ",
            "What is unsafe equipment?",
            "Which form is used?",
            "Who is the coordinator?",
        ]
    }
    assert clean_questions(raw) == [
        "How often are kiosks inspected?",
        "Who receives fault reports?",
        "When are displays replaced?",
        "What is unsafe equipment?",
        "Which form is used?",
    ]


@pytest.mark.parametrize(
    "raw", [None, [], {"questions": "x"}, {"questions": ["Only one?", "And two?"]}]
)
def test_clean_questions_needs_at_least_three(raw: object) -> None:
    assert clean_questions(raw) is None


def test_factory_builds_a_small_client_when_configured() -> None:
    llm = create_suggestion_llm(_settings())
    assert llm is not None
    assert llm.model_name == "gpt-4o-mini"


@pytest.mark.parametrize(
    "update",
    [
        {"question_suggestions_enabled": False},
        {"llm_provider": "none"},
        {"openai_api_key": None},
        {"llm_model": "stub-model"},
        {"llm_base_url": "https://stub-llm.internal/v1"},
    ],
)
def test_factory_skips_generation(update: dict[str, Any]) -> None:
    assert create_suggestion_llm(_settings(**update)) is None


def test_suggestions_are_off_in_the_test_suite() -> None:
    assert get_settings().question_suggestions_enabled is False


def _context() -> PipelineContext:
    context = PipelineContext(
        document_id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        storage_key="k",
        content_type="application/pdf",
        file_size=1,
        checksum_sha256="0" * 64,
        storage=None,  # type: ignore[arg-type]
    )
    context.state.content = DocumentContent(
        pages=(PageText(number=1, text="Some text."),), source_format="pdf"
    )
    return context


def test_step_without_llm_is_a_no_op() -> None:
    def factory() -> None:
        raise AssertionError("must not open a session")

    SuggestQuestionsStep(factory, None, 1000).run(_context())  # type: ignore[arg-type]


def test_step_never_raises_when_the_llm_fails() -> None:
    def factory() -> None:
        raise AssertionError("must not open a session")

    llm = MockLLM(error=True)
    SuggestQuestionsStep(factory, llm, 1000).run(_context())  # type: ignore[arg-type]
    assert len(llm.calls) == 1
