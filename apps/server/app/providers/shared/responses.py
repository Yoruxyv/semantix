"""Validate final generated text after provider-specific response extraction."""

from app.core.exceptions import InvalidProviderResponseError
from semantix_cache._semantics import valid_response


def validate_generation_response(value: object) -> str:
    """Apply the package text validator and map its ValueError to a public error.

    Require a nonblank string within the shared response character limit. Return
    accepted text unchanged, including surrounding whitespace. Adapters own JSON
    decoding/extraction; this helper does not inspect completion/stop reasons, tool
    calls, refusals, thought markers or full provider protocol correctness.

    Args:
        value: Extracted generated-text candidate.

    Returns:
        Original text accepted by the shared semantic validator.

    Raises:
        InvalidProviderResponseError: Text fails the shared validator; its original
            ValueError is suppressed rather than exposed as the public error cause.
    """
    try:
        return valid_response(value)
    except ValueError:
        raise InvalidProviderResponseError(
            "Generation provider returned an invalid response"
        ) from None
