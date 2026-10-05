"""Provider vector response parsing."""

import math
from typing import cast


def parse_vector(
    value: object,
    *,
    dimensions: int,
) -> list[float] | None:
    if not isinstance(value, list):
        return None
    components = cast("list[object]", value)
    if len(components) != dimensions or not all(
        isinstance(component, (int, float)) and not isinstance(component, bool)
        for component in components
    ):
        return None

    vector = [float(cast(int | float, component)) for component in components]
    return vector if all(math.isfinite(component) for component in vector) else None
