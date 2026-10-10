"""Server Gemini embedContent and generateContent wire contracts.

Application lifespan owns the injected HTTP client; these adapters never close it.
Constructors expect deployment-validated configuration. ``post_json`` applies the
retry policy, byte limit and deadline derived from the client's read timeout;
provider-specific parsing occurs after that transport call and is not retried.
Cancellation propagates during HTTP waits without guaranteeing remote rollback.
See ``app.providers.shared.transport`` and ``docs/guides/providers.md``.
"""

from collections.abc import Sequence
from typing import cast
from urllib.parse import quote

import httpx

from app.core.exceptions import InvalidProviderResponseError
from app.providers.shared.transport import (
    DEFAULT_PROVIDER_MAX_RESPONSE_BYTES,
    RetryFactory,
    create_retry_factory,
    post_json,
)
from app.providers.shared.vectors import parse_vector

RETRY_ATTEMPTS = 3
RETRY_MULTIPLIER_SECONDS = 0.5
RETRY_MAX_WAIT_SECONDS = 4.0
DEFAULT_RETRY_FACTORY = create_retry_factory(
    attempts=RETRY_ATTEMPTS,
    multiplier_seconds=RETRY_MULTIPLIER_SECONDS,
    max_wait_seconds=RETRY_MAX_WAIT_SECONDS,
)


class GeminiProvider:
    """Serve Gemini embedding and generation through their distinct model endpoints."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        base_url: str,
        embedding_model: str | None,
        generation_model: str | None,
        embedding_dimensions: int | None,
        max_new_tokens: int,
        retry_factory: RetryFactory = DEFAULT_RETRY_FACTORY,
        max_response_bytes: int = DEFAULT_PROVIDER_MAX_RESPONSE_BYTES,
    ) -> None:
        """Capture Gemini settings and strip an optional ``models/`` model prefix.

        Args:
            client: Application-owned async HTTP client.
            api_key: Credential sent in ``x-goog-api-key``.
            base_url: Validated API root, normally including its version path.
            embedding_model: Bare or ``models/``-prefixed model, or ``None``.
            generation_model: Bare or ``models/``-prefixed model, or ``None``.
            embedding_dimensions: Requested and expected vector length, or ``None``.
            max_new_tokens: Generation budget sent as ``maxOutputTokens``.
            retry_factory: Per-request policy; the default retries eligible
                transport failures for up to three attempts.
            max_response_bytes: Shared transport's buffered response byte limit.
        """
        self._client = client
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._embedding_model = (
            None if embedding_model is None else self._model_name(embedding_model)
        )
        self._generation_model = (
            None if generation_model is None else self._model_name(generation_model)
        )
        self._embedding_dimensions = embedding_dimensions
        self._max_new_tokens = max_new_tokens
        self._retry_factory = retry_factory
        self._max_response_bytes = max_response_bytes

    async def create_embedding(
        self,
        text: str,
    ) -> Sequence[float]:
        """POST text parts to the URL-encoded model's ``:embedContent`` endpoint.

        Sends ``model="models/..."``, ``content.parts`` and top-level
        ``outputDimensionality``. Extract ``embedding.values`` as finite numeric
        components excluding booleans, with exactly the configured dimensions.
        No padding, truncation or local normalization is performed; the service
        subsequently checks magnitude and normalizes the vector.

        Returns:
            The model vector at its returned scale.

        Raises:
            RuntimeError: Embedding model or dimensions are not configured.
            InvalidProviderResponseError: Embedding shape or dimensions are invalid.
        """
        if self._embedding_model is None or self._embedding_dimensions is None:
            raise RuntimeError("Gemini embedding provider is not configured")
        model_path = quote(
            self._embedding_model,
            safe="",
        )
        payload = await post_json(
            self._client,
            (f"{self._base_url}/models/{model_path}:embedContent"),
            headers=self._headers(),
            body={
                "model": f"models/{self._embedding_model}",
                "content": {
                    "parts": [
                        {
                            "text": text,
                        },
                    ],
                },
                # gemini-embedding-001 honors the supported top-level field;
                # the newer nested config can silently return the default size.
                "outputDimensionality": self._embedding_dimensions,
            },
            retry_factory=self._retry_factory,
            max_response_bytes=self._max_response_bytes,
        )
        if not isinstance(payload, dict):
            raise InvalidProviderResponseError(
                "Invalid embedding response",
            )

        embedding = cast("dict[str, object]", payload).get("embedding")
        if not isinstance(embedding, dict):
            raise InvalidProviderResponseError(
                "Embedding response contained no embedding",
            )

        vector = parse_vector(
            cast("dict[str, object]", embedding).get("values"),
            dimensions=self._embedding_dimensions,
        )
        if vector is None:
            raise InvalidProviderResponseError(
                "Invalid embedding vector",
            )
        return vector

    async def generate(self, prompt: str) -> str:
        """POST user text parts to the encoded model's ``:generateContent`` endpoint.

        Sets ``generationConfig.maxOutputTokens``. Require a first candidate with
        content and a parts list, then collect its nonblank string text parts.
        Malformed/nontext parts are skipped. This server decoder does not check
        ``finishReason``, exclude thought-marked text or reject function-call parts;
        the embedded Gemini completion parser has separate, stricter checks.

        Returns:
            Trimmed text parts from the first candidate, joined with newlines.

        Raises:
            RuntimeError: A generation model is not configured.
            InvalidProviderResponseError: Candidate/content/parts are invalid or
                contain no nonblank text.
        """
        if self._generation_model is None:
            raise RuntimeError("Gemini generation provider is not configured")
        model_path = quote(
            self._generation_model,
            safe="",
        )
        payload = await post_json(
            self._client,
            (f"{self._base_url}/models/{model_path}:generateContent"),
            headers=self._headers(),
            body={
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": prompt,
                            },
                        ],
                    },
                ],
                "generationConfig": {
                    "maxOutputTokens": self._max_new_tokens,
                },
            },
            retry_factory=self._retry_factory,
            max_response_bytes=self._max_response_bytes,
        )
        if not isinstance(payload, dict):
            raise InvalidProviderResponseError(
                "Invalid generation response",
            )

        candidates = cast("dict[str, object]", payload).get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise InvalidProviderResponseError(
                "Generation response contained no candidates",
            )

        first = cast("list[object]", candidates)[0]
        if not isinstance(first, dict):
            raise InvalidProviderResponseError(
                "Invalid generation candidate",
            )
        content = cast("dict[str, object]", first).get("content")
        if not isinstance(content, dict):
            raise InvalidProviderResponseError(
                "Generation response contained no content",
            )
        parts = cast("dict[str, object]", content).get("parts")
        if not isinstance(parts, list):
            raise InvalidProviderResponseError(
                "Generation response contained no parts",
            )

        text_parts: list[str] = []
        for part in cast("list[object]", parts):
            if not isinstance(part, dict):
                continue
            text = cast("dict[str, object]", part).get("text")
            if isinstance(text, str) and text.strip():
                text_parts.append(text.strip())

        if not text_parts:
            raise InvalidProviderResponseError(
                "Generation response contained no text",
            )
        return "\n".join(text_parts)

    def _headers(self) -> dict[str, str]:
        return {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _model_name(value: str) -> str:
        return value.removeprefix("models/")
