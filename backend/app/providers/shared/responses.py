from app.core.exceptions import InvalidProviderResponseError
from semantix_cache._semantics import valid_response


def validate_generation_response(value: object) -> str:
    try:
        return valid_response(value)
    except ValueError:
        raise InvalidProviderResponseError(
            "Generation provider returned an invalid response"
        ) from None
