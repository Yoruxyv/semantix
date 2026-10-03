"""Cache response metadata helpers."""

from app.core.limits import MAX_RESPONSE_PREVIEW_LENGTH

TRUNCATED_RESPONSE_PREVIEW_MESSAGE = (
    "Response exceeds the preview limit. Inspect the complete response."
)


def response_preview(response: str) -> str:
    if len(response) <= MAX_RESPONSE_PREVIEW_LENGTH:
        return response
    return TRUNCATED_RESPONSE_PREVIEW_MESSAGE


def response_preview_is_truncated(response: str) -> bool:
    return len(response) > MAX_RESPONSE_PREVIEW_LENGTH
