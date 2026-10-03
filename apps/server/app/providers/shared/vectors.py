"""Provider vector response parsing."""

import math
from typing import cast


def parse_vector(
    value: object,
    *,
    dimensions: int,
) -> list[float] | None:
    if (
        not isinstance(value, list)
        or len(value) != dimensions
        or not all(
            isinstance(component, (int, float)) and not isinstance(component, bool)
            for component in value
        )
    ):
        return None

    vector = [float(cast(int | float, component)) for component in value]
    return vector if all(math.isfinite(component) for component in vector) else None
