import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from symspellpy import SymSpell

from app.core.config import Settings
from app.factory import create_app
from app.query.domain.normalization import (
    SymSpellPromptNormalizer,
    create_prompt_normalizer,
)


@pytest.fixture(scope="module")
def normalizer() -> SymSpellPromptNormalizer:
    return SymSpellPromptNormalizer.load(max_edit_distance=2)


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("semntic caching", "semantic caching"),
        ("cahcing", "caching"),
        ("ex plain", "explain"),
    ],
)
def test_normalizes_supported_typo_patterns(
    normalizer: SymSpellPromptNormalizer,
    prompt: str,
    expected: str,
) -> None:
    assert normalizer.normalize(prompt) == expected


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("What is Semantix?", "What is Semantix"),
        (
            "How does pgvector store a namespace?",
            "How does pgvector store a namespace",
        ),
        ("Compare OpenAI and FastAPI", "Compare OpenAI and FastAPI"),
    ],
)
def test_preserves_project_terms(
    normalizer: SymSpellPromptNormalizer,
    prompt: str,
    expected: str,
) -> None:
    assert normalizer.normalize(prompt) == expected


@pytest.mark.parametrize(
    "prompt",
    [
        "do not cache this",
        "never reuse private data",
        "cache without sharing",
        "we must not reuse this",
        "we should not cache this",
        "we may cache this",
        "can we cache this",
        "no cache reuse",
    ],
)
def test_preserves_negation_modality_and_short_function_words(
    normalizer: SymSpellPromptNormalizer,
    prompt: str,
) -> None:
    assert normalizer.normalize(prompt) == prompt


def test_disabled_normalizer_does_not_load_dictionary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> bool:
        raise AssertionError("dictionary should not be loaded")

    monkeypatch.setattr(SymSpell, "load_dictionary", fail_if_called)

    normalize = create_prompt_normalizer(
        enabled=False,
        max_edit_distance=2,
    )

    assert normalize("semntic caching") == "semntic caching"


def test_enabled_normalizer_fails_when_dictionary_cannot_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_load(*args: object, **kwargs: object) -> bool:
        return False

    monkeypatch.setattr(SymSpell, "load_dictionary", fail_to_load)

    with pytest.raises(
        RuntimeError,
        match="bundled SymSpell English frequency dictionary",
    ):
        create_prompt_normalizer(
            enabled=True,
            max_edit_distance=2,
        )


def test_enabled_dictionary_failure_stops_application_startup(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
) -> None:
    def fail_to_load(*args: object, **kwargs: object) -> bool:
        return False

    monkeypatch.setattr(SymSpell, "load_dictionary", fail_to_load)
    enabled_settings = settings.model_copy(
        update={"prompt_typo_correction_enabled": True}
    )

    with (
        pytest.raises(
            RuntimeError,
            match="bundled SymSpell English frequency dictionary",
        ),
        TestClient(create_app(enabled_settings)),
    ):
        pass


def test_typo_correction_settings_default_to_disabled(
    settings: Settings,
) -> None:
    assert settings.prompt_typo_correction_enabled is False
    assert settings.prompt_typo_max_edit_distance == 2


@pytest.mark.parametrize("distance", [-1, 4])
def test_typo_edit_distance_is_bounded(
    settings: Settings,
    distance: int,
) -> None:
    values = settings.model_dump()
    values["prompt_typo_max_edit_distance"] = distance

    with pytest.raises(ValidationError):
        Settings.model_validate(values)
