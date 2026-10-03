from app.core.config import Settings
from app.lifecycle import _fingerprint
from app.providers.configuration import selected_generation_configuration

ORIGINS = ["http://localhost:5173"]


def generation_settings(
    *,
    api_key: str = "secret-a",
    base_url: str = "https://private-a.example.test/v1",
    model: str = "model-a",
    max_new_tokens: int = 512,
    max_response_bytes: int = 4_194_304,
) -> Settings:
    return Settings(
        embedding_provider="mock",
        generation_provider="openai",
        openai_api_key=api_key,
        openai_base_url=base_url,
        openai_generation_model=model,
        generation_max_new_tokens=max_new_tokens,
        provider_max_response_bytes=max_response_bytes,
        allowed_origins=ORIGINS,
    )


def generation_fingerprint(settings: Settings) -> str:
    return _fingerprint(selected_generation_configuration(settings))


def test_generation_configuration_fingerprint_is_stable_and_safe() -> None:
    first = generation_settings()
    same_semantics = generation_settings(
        api_key="secret-b",
        base_url="https://private-b.example.test/v1",
    )

    assert generation_fingerprint(first) == generation_fingerprint(same_semantics)
    safe_configuration = selected_generation_configuration(first)
    assert safe_configuration == {
        "provider": "openai",
        "model": "model-a",
        "max_new_tokens": 512,
        "max_response_bytes": 4_194_304,
    }
    serialized = repr(safe_configuration)
    assert "secret-a" not in serialized
    assert "private-a.example.test" not in serialized


def test_generation_configuration_fingerprint_changes_with_execution_inputs() -> None:
    baseline = generation_fingerprint(generation_settings())

    for changed in (
        generation_settings(model="model-b"),
        generation_settings(max_new_tokens=256),
        generation_settings(max_response_bytes=2_000_000),
    ):
        assert generation_fingerprint(changed) != baseline
