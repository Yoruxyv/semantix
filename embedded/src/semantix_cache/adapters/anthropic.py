"""Anthropic generation; use a structural custom adapter for other embedding APIs.

See https://github.com/Yoruxyv/semantix/blob/main/docs/embedded-providers.md#custom-integrations.
"""

from ..errors import GenerationError
from ._http import (
    HTTPAdapter,
    configured_key,
    httpx,
    positive_integer,
    request_text,
)
from ._parsing import anthropic_text

__all__ = ["AnthropicGenerationAdapter"]


class AnthropicGenerationAdapter(HTTPAdapter):
    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        api_key: str,
        model: str,
        max_new_tokens: int = 512,
        base_url: str = "https://api.anthropic.com",
        timeout_seconds: float = 30.0,
        max_response_bytes: int = 1048576,
    ) -> None:
        super().__init__(
            client=client,
            model=model,
            base_url=base_url,
            headers={
                "x-api-key": configured_key(api_key),
                "anthropic-version": "2023-06-01",
            },
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            error=GenerationError,
        )
        self._max_new_tokens = positive_integer(max_new_tokens)

    async def generate(self, prompt: str) -> str:
        self._lifecycle.check_open()
        request_text(prompt)
        return await self._post(
            "/v1/messages",
            {
                "model": self._model,
                "max_tokens": self._max_new_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            anthropic_text,
        )
