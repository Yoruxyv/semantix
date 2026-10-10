"""Server Hugging Face feature-extraction and chat wire contracts.

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
import numpy as np

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


def _rows(
    value: object,
    *,
    dimensions: int,
) -> list[list[float]] | None:
    """Decode a vector, row matrix or recursively singleton-wrapped rows.

    Try a complete dimension-matched vector first; otherwise unwrap a single
    nested item or require every matrix row to pass numeric vector validation.
    Zero rows are allowed here. Pooling and final service normalization happen
    later; malformed shapes return ``None``.
    """
    direct = parse_vector(value, dimensions=dimensions)
    if direct is not None:
        return [direct]

    if not isinstance(value, list) or not value:
        return None

    items = cast("list[object]", value)
    if len(items) == 1:
        nested = _rows(
            items[0],
            dimensions=dimensions,
        )
        if nested is not None:
            return nested

    result: list[list[float]] = []
    for item in items:
        row = parse_vector(
            item,
            dimensions=dimensions,
        )
        if row is None:
            return None
        result.append(row)

    return result or None


class HuggingFaceProvider:
    """Use independent Hugging Face feature-extraction and chat configurations."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        inference_base_url: str | None,
        chat_base_url: str | None,
        embedding_model: str | None,
        generation_model: str | None,
        embedding_dimensions: int | None,
        max_new_tokens: int,
        retry_factory: RetryFactory = DEFAULT_RETRY_FACTORY,
        max_response_bytes: int = DEFAULT_PROVIDER_MAX_RESPONSE_BYTES,
    ) -> None:
        """Capture feature-extraction and chat settings with a borrowed client.

        Args:
            client: Application-owned async HTTP client.
            api_key: Bearer credential for both API paths.
            inference_base_url: Validated root preceding the encoded model path,
                or ``None`` when embedding is not configured.
            chat_base_url: Validated chat API root, or ``None`` when unconfigured.
            embedding_model: Model path for feature extraction, or ``None``.
            generation_model: Chat payload's model identifier, or ``None``.
            embedding_dimensions: Expected row and pooled-vector length, or ``None``.
            max_new_tokens: Generation budget sent as ``max_tokens``.
            retry_factory: Per-request policy; the default retries eligible
                transport failures for up to three attempts.
            max_response_bytes: Shared transport's buffered response byte limit.
        """
        self._client = client
        self._api_key = api_key
        self._inference_base_url = (
            None if inference_base_url is None else inference_base_url.rstrip("/")
        )
        self._chat_base_url = (
            None if chat_base_url is None else chat_base_url.rstrip("/")
        )
        self._embedding_model = embedding_model
        self._generation_model = generation_model
        self._embedding_dimensions = embedding_dimensions
        self._max_new_tokens = max_new_tokens
        self._retry_factory = retry_factory
        self._max_response_bytes = max_response_bytes

    async def create_embedding(
        self,
        text: str,
    ) -> Sequence[float]:
        """Request feature extraction and mean-pool validated rows in float64.

        POST to ``/{model}/pipeline/feature-extraction`` under the inference root,
        quoting the model while preserving slashes. Send ``inputs=[text]`` and
        ``normalize=True``. Accept a flat vector, matrix of dimension-matched rows
        or singleton wrappers understood by ``_rows``; average rows along axis 0.
        Reject a wrong-size or nonfinite pooled result. The request's normalization
        flag does not locally normalize the mean: EmbeddingService does that and
        rejects invalid magnitude before cache use.

        Returns:
            The pooled float vector, without local unit-length normalization.

        Raises:
            RuntimeError: Inference URL, embedding model or dimensions are absent.
            InvalidProviderResponseError: Rows or the pooled vector are invalid.
        """
        if (
            self._inference_base_url is None
            or self._embedding_model is None
            or self._embedding_dimensions is None
        ):
            raise RuntimeError("Hugging Face embedding provider is not configured")
        model_path = quote(
            self._embedding_model,
            safe="/",
        )
        endpoint = (
            f"{self._inference_base_url}/{model_path}/pipeline/feature-extraction"
        )
        payload = await post_json(
            self._client,
            endpoint,
            headers=self._headers(),
            body={
                "inputs": [text],
                "normalize": True,
            },
            retry_factory=self._retry_factory,
            max_response_bytes=self._max_response_bytes,
        )
        rows = _rows(
            payload,
            dimensions=self._embedding_dimensions,
        )
        if rows is None:
            raise InvalidProviderResponseError(
                "Invalid embedding shape",
            )

        vector = np.mean(
            np.asarray(rows, dtype=np.float64),
            axis=0,
        )
        if (
            vector.shape != (self._embedding_dimensions,)
            or not np.isfinite(vector).all()
        ):
            raise InvalidProviderResponseError(
                "Invalid embedding vector",
            )
        return [float(component) for component in vector]

    async def generate(self, prompt: str) -> str:
        """POST a user message to the chat root's ``/chat/completions`` endpoint.

        Sends ``max_tokens`` and ``stream=False``. Decode only the first choice's
        message content, requiring nonblank text. This provider owns its decoder
        independently of OpenAI and does not check finish reasons, tool calls or
        refusals here. Server workflows validate returned text afterward.

        Returns:
            The first choice's text with surrounding whitespace removed.

        Raises:
            RuntimeError: Chat URL or generation model is not configured.
            InvalidProviderResponseError: Choices, message or text are invalid.
        """
        if self._chat_base_url is None or self._generation_model is None:
            raise RuntimeError("Hugging Face generation provider is not configured")
        payload = await post_json(
            self._client,
            f"{self._chat_base_url}/chat/completions",
            headers=self._headers(),
            body={
                "model": self._generation_model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "max_tokens": self._max_new_tokens,
                "stream": False,
            },
            retry_factory=self._retry_factory,
            max_response_bytes=self._max_response_bytes,
        )
        if not isinstance(payload, dict):
            raise InvalidProviderResponseError(
                "Invalid chat-completion response",
            )

        choices = cast("dict[str, object]", payload).get("choices")
        if not isinstance(choices, list) or not choices:
            raise InvalidProviderResponseError(
                "Chat response contained no choices",
            )

        first_choice = cast("list[object]", choices)[0]
        if not isinstance(first_choice, dict):
            raise InvalidProviderResponseError(
                "Invalid chat choice",
            )

        message = cast("dict[str, object]", first_choice).get("message")
        if not isinstance(message, dict):
            raise InvalidProviderResponseError(
                "Chat response contained no message",
            )

        content = cast("dict[str, object]", message).get("content")
        if not isinstance(content, str) or not content.strip():
            raise InvalidProviderResponseError(
                "Chat response contained no text",
            )
        return content.strip()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
