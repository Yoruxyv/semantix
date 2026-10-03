import math

from app.providers.shared.vectors import parse_vector


def test_parses_finite_vector_with_expected_dimensions() -> None:
    assert parse_vector(
        [1, 0.5, 0, -1],
        dimensions=4,
    ) == [1.0, 0.5, 0.0, -1.0]


def test_rejects_invalid_vector_components_and_shape() -> None:
    assert (
        parse_vector(
            [1.0],
            dimensions=4,
        )
        is None
    )
    assert (
        parse_vector(
            [True, 0.0, 0.0, 0.0],
            dimensions=4,
        )
        is None
    )
    assert (
        parse_vector(
            [math.inf, 0.0, 0.0, 0.0],
            dimensions=4,
        )
        is None
    )
