"""PostgreSQL identifiers and immutable binding configuration; no driver or pool."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...._semantics import finite_number, resolve_ttl
from ....errors import CacheConfigurationError
from ....models import EmbeddingSpace

_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}", re.ASCII)


def _quote(name: str) -> str:
    # Catalog-owned extension identifiers may use mixed case; escape every quote.
    return '"' + name.replace('"', '""') + '"'


def _positive_timeout(value: float) -> float:
    result = finite_number(value, minimum=0.0, maximum=86400.0)
    if result == 0:
        raise ValueError("Timeout must be positive")
    return result


@dataclass(frozen=True)
class _Configuration:
    space: EmbeddingSpace
    schema: str
    prefix: str
    capacity: int
    ttl: float | None
    timeout: float
    close_timeout: float

    def __post_init__(self) -> None:
        try:
            if not isinstance(self.space, EmbeddingSpace):
                raise CacheConfigurationError("Invalid PostgreSQL embedding space")
            space = EmbeddingSpace.model_validate(self.space.model_dump())
            if (
                space.dimensions > 16000
                or len(space.identity) > 1024
                or "\0" in space.identity
            ):
                raise ValueError("Space exceeds database limits")
            if (
                not isinstance(self.schema, str)
                or _IDENTIFIER.fullmatch(self.schema) is None
            ):
                raise ValueError("Invalid schema")
            if self.schema.startswith("pg_") or self.schema == "information_schema":
                raise ValueError("Reserved schema")
            if not isinstance(self.prefix, str) or (
                self.prefix and _IDENTIFIER.fullmatch(self.prefix) is None
            ):
                raise ValueError("Invalid prefix")
            for suffix in (
                "cache_entries",
                "binding_state",
                "schema_migrations",
                "scope_idx",
            ):
                if _IDENTIFIER.fullmatch(self.prefix + suffix) is None:
                    raise ValueError("Identifier exceeds database limits")
            if (
                isinstance(self.capacity, bool)
                or not isinstance(self.capacity, int)
                or not 1 <= self.capacity <= 100000
            ):
                raise ValueError("Invalid capacity")
            object.__setattr__(self, "space", space)
            object.__setattr__(self, "ttl", resolve_ttl(None, self.ttl))
            object.__setattr__(self, "timeout", _positive_timeout(self.timeout))
            object.__setattr__(
                self, "close_timeout", _positive_timeout(self.close_timeout)
            )
        except ValueError:
            raise CacheConfigurationError(
                "Invalid PostgreSQL store configuration"
            ) from None

    def relation(self, suffix: str) -> str:
        return _quote(self.schema) + "." + _quote(self.prefix + suffix)

    @property
    def lock_key(self) -> str:
        return "semantix-cache:" + self.schema + ":" + self.prefix
