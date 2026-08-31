import os

from pydantic import SecretStr

from app.core.config import Settings
from app.factory import create_app
from app.providers.extension import (
    ProviderBuildContext,
    ProviderRegistration,
    create_default_provider_registry,
)

CUSTOM_SECRET = os.environ["SEMANTIX_TEST_CUSTOM_SECRET"]
BUILTIN_SECRET = os.environ["SEMANTIX_TEST_BUILTIN_SECRET"]


class SecretFailureProvider:
    async def generate(self, prompt: str) -> str:
        try:
            raise ValueError(f"nested provider failure: {BUILTIN_SECRET}")
        except ValueError as exc:
            raise RuntimeError(f"provider failure: {CUSTOM_SECRET}") from exc


def build_provider(_context: ProviderBuildContext) -> SecretFailureProvider:
    return SecretFailureProvider()


settings = Settings(
    embedding_provider="mock",
    generation_provider="test-secret-failure",
    hf_api_key=SecretStr(BUILTIN_SECRET),
    openai_api_key=None,
    anthropic_api_key=None,
    gemini_api_key=None,
    database_url=None,
    cache_backend="memory",
    evaluation_dataset_storage="session",
    evaluation_run_history_storage="disabled",
    allowed_origins=["http://localhost:5173"],
    rate_limit="1000/minute",
)
registry = create_default_provider_registry(settings)
registry.register(
    ProviderRegistration(
        name="test-secret-failure",
        capabilities=frozenset({"generation"}),
        builder=build_provider,
        generation_metadata={"provider": "test-secret-failure", "model": "v1"},
        secrets=(SecretStr(CUSTOM_SECRET),),
    )
)
app = create_app(settings, provider_registry=registry)
