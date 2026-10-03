import httpx

from app.core.exceptions import InvalidProviderResponseError
from app.providers.shared.transport import (
    DEFAULT_PROVIDER_MAX_RESPONSE_BYTES,
    RetryFactory,
    create_retry_factory,
    post_json,
)

RETRY_ATTEMPTS = 3
RETRY_MULTIPLIER_SECONDS = 0.5
RETRY_MAX_WAIT_SECONDS = 4.0
DEFAULT_RETRY_FACTORY = create_retry_factory(
    attempts=RETRY_ATTEMPTS,
    multiplier_seconds=RETRY_MULTIPLIER_SECONDS,
    max_wait_seconds=RETRY_MAX_WAIT_SECONDS,
)
ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicProvider:
    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        base_url: str,
        generation_model: str,
        max_new_tokens: int,
        retry_factory: RetryFactory = DEFAULT_RETRY_FACTORY,
        max_response_bytes: int = DEFAULT_PROVIDER_MAX_RESPONSE_BYTES,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._generation_model = generation_model
        self._max_new_tokens = max_new_tokens
        self._retry_factory = retry_factory
        self._max_response_bytes = max_response_bytes

    async def generate(self, prompt: str) -> str:
        payload = await post_json(
            self._client,
            f"{self._base_url}/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": ANTHROPIC_API_VERSION,
                "Content-Type": "application/json",
            },
            body={
                "model": self._generation_model,
                "max_tokens": self._max_new_tokens,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
            },
            retry_factory=self._retry_factory,
            max_response_bytes=self._max_response_bytes,
        )
        if not isinstance(payload, dict):
            raise InvalidProviderResponseError(
                "Invalid message response",
            )

        content = payload.get("content")
        if not isinstance(content, list) or not content:
            raise InvalidProviderResponseError(
                "Message response contained no content",
            )

        text_blocks: list[str] = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                text_blocks.append(text.strip())

        if not text_blocks:
            raise InvalidProviderResponseError(
                "Message response contained no text",
            )
        return "\n".join(text_blocks)
