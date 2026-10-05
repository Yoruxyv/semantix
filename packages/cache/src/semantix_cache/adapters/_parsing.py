"""Provider response decoding with payload-free validation errors."""

import math
from collections.abc import Sequence
from typing import cast

import numpy as np

from .._semantics import normalized_vector, valid_response
from ..errors import EmbeddingError, GenerationError


def components(value: object, dimensions: int) -> tuple[float, ...]:
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
    result = components(value, dimensions)
    try:
        normalized_vector(result, dimensions=dimensions)
    except ValueError:
        raise EmbeddingError("Provider returned an invalid embedding vector") from None
    return result


def pooled_vector(value: object, dimensions: int) -> Sequence[float]:
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
    choice = first(mapping(payload).get("choices"))
    if choice.get("finish_reason") != "stop":
        raise GenerationError("Provider generation did not finish with completed text")
    message = mapping(choice.get("message"))
    if message.get("tool_calls") or message.get("refusal"):
        raise GenerationError("Provider generation requires application handling")
    return text(message.get("content"))


def parts_text(parts: object, *, typed: bool = False) -> str:
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
    message = mapping(payload)
    if message.get("done") is not True or message.get("done_reason") not in (
        None,
        "stop",
    ):
        raise GenerationError("Provider generation did not finish with completed text")
    return text(message.get("response"))


def ollama_vector(payload: object, dimensions: int) -> Sequence[float]:
    embeddings = mapping(payload).get("embeddings")
    if not isinstance(embeddings, list) or len(cast("list[object]", embeddings)) != 1:
        raise EmbeddingError("Provider returned an invalid embedding batch")
    return vector(cast("list[object]", embeddings)[0], dimensions)


def openai_vector(payload: object, dimensions: int) -> Sequence[float]:
    data = mapping(payload).get("data")
    if not isinstance(data, list) or len(cast("list[object]", data)) != 1:
        raise EmbeddingError("Provider returned an invalid embedding batch")
    return vector(mapping(cast("list[object]", data)[0]).get("embedding"), dimensions)
