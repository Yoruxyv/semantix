"""Provider vector response parsing."""

import math
from typing import cast


def parse_vector(
    value: object,
    *,
    dimensions: int,
) -> list[float] | None:
    """Parse a dimension-matching list of finite numeric components.

    Accept int/float components and subclasses, explicitly excluding bool, and
    convert to Python floats. Zero magnitude is allowed; normalization belongs to
    ``app.embedding.service``. Integer-to-float overflow is not caught here.

    Args:
        value: Provider-decoded JSON value, requiring an outer list.
        dimensions: Required component count supplied by the caller.

    Returns:
        Converted list, or None for checked shape/type/nonfinite failures.

    Raises:
        OverflowError: A numeric component cannot be represented by float conversion.
    """
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
