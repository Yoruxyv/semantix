"""Cache response metadata helpers.

Responses within the character limit are returned intact; longer responses use
the fixed omission message rather than a partial substring. The truncation flag
describes that limit, not response validity or completeness of other metadata.
Prompts, previews and complete responses can expose sensitive user content;
these helpers neither redact it nor authorize access.
"""

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
