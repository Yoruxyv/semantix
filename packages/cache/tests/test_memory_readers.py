"""Reader query normalization preserves the shared validation contract."""

from collections.abc import Sequence
from fractions import Fraction
from typing import cast

import numpy as np
import pytest

from semantix_cache import memory
from semantix_cache._semantics import normalized_vector


@pytest.mark.parametrize("dimensions", [2, 384, 1536, 3072])
def test_plain_float_query_matches_original_bits(dimensions: int) -> None:
    rng = np.random.default_rng(8124)
    for raw in rng.normal(size=(20, dimensions)):
        values = tuple(float(v) for v in raw)
        actual = memory._query_vector(values, dimensions=dimensions)
        expected = normalized_vector(values, dimensions=dimensions)
        assert actual.tobytes() == expected.tobytes()
        assert actual.flags.owndata


@pytest.mark.parametrize(
    "values",
    [
        (0.0, 0.0),
        (float("nan"), 1.0),
        (float("inf"), 1.0),
        (1e308, 1e308),
        (np.finfo(np.float64).eps.item(), 0.0),
        (float(np.nextafter(np.finfo(np.float64).eps, np.inf)), 0.0),
        (1e-300, 1e-300),
        (1.0,),
        (True, 1.0),
        ("1", 0.0),
        (10**400, 1),
        (Fraction(1, 3), Fraction(2, 3)),
        [1.0, 2.0],
        (np.float64(1), np.float64(2)),
        np.array([1.0, 2.0]),
        np.array([[1.0, 2.0]]),
        "12",
        None,
    ],
)
def test_query_validation_matches_shared_contract(values: object) -> None:
    query = cast(Sequence[float], values)
    try:
        expected = normalized_vector(query, dimensions=2)
    except ValueError as exc:
        expected_error = (type(exc), str(exc))
    else:
        assert memory._query_vector(query, dimensions=2).tobytes() == expected.tobytes()
        return
    with pytest.raises(expected_error[0]) as caught:
        memory._query_vector(query, dimensions=2)
    assert str(caught.value) == expected_error[1]
