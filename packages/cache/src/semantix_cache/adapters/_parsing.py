"""Provider response decoding with payload-free validation errors.

Internal helpers implement the currently supported integrations' schemas;
they are not public extension APIs. OpenAI and Hugging Face currently reuse
``chat_text``, without requiring their future response contracts to converge.
Each provider adapter chooses its payload and parser independently.
"""

import math
from collections.abc import Sequence
from typing import cast

import numpy as np

from .._semantics import normalized_vector, valid_response
from ..errors import EmbeddingError, GenerationError


def components(value: object, dimensions: int) -> tuple[float, ...]:
    """Convert a dimension-matched JSON list of finite numbers to float components.

    Reject booleans, nonnumeric items and float-conversion overflow with
    EmbeddingError. Zero rows are allowed here so token pooling can use them;
    final magnitude validation belongs to ``vector``.
    """
    if not isinstance(value, list):
        raise EmbeddingError("Provider returned an invalid embedding vector")
    items = cast("list[object]", value)
    if len(items) != dimensions or any(
        isinstance(item, bool) or not isinstance(item, (int, float)) for item in items
    ):
        raise EmbeddingError("Provider returned an invalid embedding vector")
    try:
        result = tuple(float(cast("int | float", item)) for item in items)
    except OverflowError:
        raise EmbeddingError("Provider returned an invalid embedding vector") from None
    if not all(math.isfinite(item) for item in result):
        raise EmbeddingError("Provider returned an invalid embedding vector")
    return result


def vector(value: object, dimensions: int) -> Sequence[float]:
    """Validate finite components and nonzero usable magnitude, preserving scale.

    Run normalized_vector for validation but discard its normalized result;
    return the original float components. The cache normalizes for comparison.
    """
    result = components(value, dimensions)
    try:
        normalized_vector(result, dimensions=dimensions)
    except ValueError:
        raise EmbeddingError("Provider returned an invalid embedding vector") from None
    return result


def pooled_vector(value: object, dimensions: int) -> Sequence[float]:
    """Unwrap singleton lists and mean-pool dimension-matched token rows in float64.

    A flat vector is validated directly. Matrix rows use component validation,
    allowing zero rows; the pooled result must still pass final vector/magnitude
    validation. Reject empty, malformed or nonfinite output with EmbeddingError,
    without returning the normalized validation copy.
    """
    while (
        isinstance(value, list)
        and len(items := cast("list[object]", value)) == 1
        and isinstance(items[0], list)
    ):
        value = cast("list[object]", items[0])
    if not isinstance(value, list) or not value:
        raise EmbeddingError("Provider returned an invalid embedding shape")
    items = cast("list[object]", value)
    if not isinstance(items[0], list):
        return vector(items, dimensions)
    rows = [components(row, dimensions) for row in items]
    with np.errstate(over="ignore", invalid="ignore"):
        pooled = np.mean(np.asarray(rows, dtype=np.float64), axis=0)
    return vector(pooled.tolist(), dimensions)


def text(value: object) -> str:
    """Validate bounded nonblank generated text before stripping edge whitespace."""
    try:
        return valid_response(value).strip()
    except ValueError:
        raise GenerationError("Provider returned invalid completed text") from None


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return cast("dict[str, object]", value)


def first(value: object) -> dict[str, object]:
    return (
        mapping(cast("list[object]", value)[0])
        if isinstance(value, list) and value
        else {}
    )


def chat_text(payload: object) -> str:
    """Extract first-choice chat text only after ``finish_reason="stop"``.

    Reject truthy tool_calls or refusal fields and validate message content as
    nonblank text within the shared output bound. Used by the current OpenAI
    and Hugging Face integrations; their wire contracts remain independently owned.
    """
    choice = first(mapping(payload).get("choices"))
    if choice.get("finish_reason") != "stop":
        raise GenerationError("Provider generation did not finish with completed text")
    message = mapping(choice.get("message"))
    if message.get("tool_calls") or message.get("refusal"):
        raise GenerationError("Provider generation requires application handling")
    return text(message.get("content"))


def parts_text(parts: object, *, typed: bool = False) -> str:
    """Join nonblank text parts, omitting entries marked ``thought is True``.

    When ``typed`` is true, include only blocks with type ``text``. Ignore
    malformed/nontext entries, then validate the joined text and its length.
    The provider parser separately decides whether tool output is acceptable.
    """
    if not isinstance(parts, list):
        raise GenerationError("Provider returned invalid completed text")
    pieces = [
        piece.strip()
        for part in map(mapping, cast("list[object]", parts))
        if (not typed or part.get("type") == "text")
        and part.get("thought") is not True
        and isinstance(piece := part.get("text"), str)
        and piece.strip()
    ]
    return text("\n".join(pieces))


def gemini_text(payload: object) -> str:
    """Require first-candidate STOP completion and reject any functionCall part.

    Decode candidate content parts through parts_text, excluding thoughts and
    validating the remaining joined text. Invalid completion/output raises
    GenerationError; later candidates are not fallback answers.
    """
    candidate = first(mapping(payload).get("candidates"))
    if candidate.get("finishReason") != "STOP":
        raise GenerationError("Provider generation did not finish with completed text")
    parts = mapping(candidate.get("content")).get("parts")
    if isinstance(parts, list):
        parts = cast("list[object]", parts)
        if any("functionCall" in mapping(part) for part in parts):
            raise GenerationError("Provider generation requires application handling")
    return parts_text(parts)


def anthropic_text(payload: object) -> str:
    """Require end_turn or stop_sequence completion and reject tool_use blocks.

    Join typed text blocks through parts_text, excluding thoughts and checking
    the completed text bound. Invalid completion/output raises GenerationError.
    """
    message = mapping(payload)
    if message.get("stop_reason") not in ("end_turn", "stop_sequence"):
        raise GenerationError("Provider generation did not finish with completed text")
    content = message.get("content")
    if isinstance(content, list):
        content = cast("list[object]", content)
        if any(mapping(block).get("type") == "tool_use" for block in content):
            raise GenerationError("Provider generation requires application handling")
    return parts_text(content, typed=True)


def ollama_text(payload: object) -> str:
    """Require done=True and a missing/null or stop done_reason before decoding text.

    Validate response as bounded nonblank text; invalid completion/output
    raises GenerationError.
    """
    message = mapping(payload)
    if message.get("done") is not True or message.get("done_reason") not in (
        None,
        "stop",
    ):
        raise GenerationError("Provider generation did not finish with completed text")
    return text(message.get("response"))


def ollama_vector(payload: object, dimensions: int) -> Sequence[float]:
    """Require exactly one Ollama embedding before vector/magnitude validation."""
    embeddings = mapping(payload).get("embeddings")
    if not isinstance(embeddings, list) or len(cast("list[object]", embeddings)) != 1:
        raise EmbeddingError("Provider returned an invalid embedding batch")
    return vector(cast("list[object]", embeddings)[0], dimensions)


def openai_vector(payload: object, dimensions: int) -> Sequence[float]:
    """Require exactly one OpenAI data item before vector/magnitude validation."""
    data = mapping(payload).get("data")
    if not isinstance(data, list) or len(cast("list[object]", data)) != 1:
        raise EmbeddingError("Provider returned an invalid embedding batch")
    return vector(mapping(cast("list[object]", data)[0]).get("embedding"), dimensions)
