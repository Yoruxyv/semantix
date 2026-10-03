import pytest

from app.core.exceptions import InvalidProviderResponseError
from app.core.limits import MAX_RESPONSE_LENGTH
from app.providers.shared.responses import validate_generation_response


@pytest.mark.parametrize(
    "value",
    [
        None,
        42,
        "",
        " \n\t ",
        "x" * (MAX_RESPONSE_LENGTH + 1),
    ],
    ids=["none", "integer", "empty", "blank", "oversized"],
)
def test_generation_response_validation_rejects_invalid_values(
    value: object,
) -> None:
    with pytest.raises(InvalidProviderResponseError):
        validate_generation_response(value)


def test_generation_response_validation_accepts_the_maximum_length() -> None:
    response = "x" * MAX_RESPONSE_LENGTH

    assert validate_generation_response(response) == response
