import os

from pydantic import SecretStr
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_none,
)

from app.core.config import Settings
from app.core.exceptions import ProviderRetryableError
from app.factory import create_app
from app.providers.extension import (
    ProviderBuildContext,
    ProviderRegistration,
    create_default_provider_registry,
    post_json,
)

PROVIDER_URL = os.environ["SEMANTIX_TEST_PROVIDER_URL"]
CUSTOM_SECRET = os.environ["SEMANTIX_TEST_CUSTOM_SECRET"]
BUILTIN_SECRET = os.environ["SEMANTIX_TEST_BUILTIN_SECRET"]


def no_retry() -> AsyncRetrying:
    return AsyncRetrying(
        retry=retry_if_exception_type(ProviderRetryableError),
        stop=stop_after_attempt(1),
        wait=wait_none(),
        reraise=True,
    )


class ProviderUrlTestProvider:
    def __init__(self, context: ProviderBuildContext) -> None:
        self._client = context.client
        self._max_response_bytes = context.provider_max_response_bytes

    async def generate(self, prompt: str) -> str:
        payload = await post_json(
            self._client,
            PROVIDER_URL,
            headers={"Authorization": f"Bearer {CUSTOM_SECRET}"},
            body={"prompt": prompt},
            retry_factory=no_retry,
            max_response_bytes=self._max_response_bytes,
        )
        response = payload.get("response") if isinstance(payload, dict) else None
        if not isinstance(response, str):
            raise ValueError("provider returned an invalid response")
        return response


def build_provider(context: ProviderBuildContext) -> ProviderUrlTestProvider:
    return ProviderUrlTestProvider(context)


settings = Settings(
    embedding_provider="mock",
    generation_provider="test-provider-url",
    hf_api_key=SecretStr(BUILTIN_SECRET),
    openai_api_key=None,
    anthropic_api_key=None,
    gemini_api_key=None,
    provider_timeout_seconds=0.2,
    database_url=None,
    cache_backend="memory",
    evaluation_dataset_storage="session",
    evaluation_run_history_storage="disabled",
    auth_mode="disabled",
    allowed_origins=["http://localhost:5173"],
    rate_limit="1000/minute",
)
registry = create_default_provider_registry(settings)
registry.register(
    ProviderRegistration(
        name="test-provider-url",
        capabilities=frozenset({"generation"}),
        builder=build_provider,
        generation_metadata={"provider": "test-provider-url", "model": "v1"},
        secrets=(SecretStr(CUSTOM_SECRET),),
    )
)
app = create_app(settings, provider_registry=registry)
