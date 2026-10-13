"""Restricted MySQL connection policy, validated before network access."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .._semantics import finite_number, resolve_ttl
from ..errors import CacheConfigurationError
from ..models import EmbeddingSpace
from ._mysql_format import safe

IO_TIMEOUT = 0.5
# Durable provisioning can exceed a normal cache read stall.
SETUP_READ_TIMEOUT = 2.0
CONNECT_TIMEOUT = 2.0


def timeout(value: float) -> float:
    result = finite_number(value, minimum=0.0, maximum=86400.0)
    if result == 0:
        raise ValueError("Timeout must be positive")
    return result


@dataclass(frozen=True, repr=False)
class Configuration:
    address: str
    port: int
    tls_hostname: str
    ca_file: Path
    user: str
    password: bytes
    database: str
    space: EmbeddingSpace
    capacity: int
    ttl: float | None
    timeout: float
    close_timeout: float

    def __post_init__(self) -> None:
        try:
            if str(ipaddress.IPv4Address(self.address)) != self.address:
                raise ValueError("Noncanonical address")
            if type(self.port) is not int or not 1 <= self.port <= 65535:
                raise ValueError("Invalid port")
            if (
                not isinstance(self.tls_hostname, str)
                or not self.tls_hostname
                or len(self.tls_hostname) > 253
                or "\0" in self.tls_hostname
                or not isinstance(self.user, str)
                or not self.user
                or "\0" in self.user
                or not isinstance(self.password, bytes)
                or b"\0" in self.password
                or not isinstance(self.database, str)
                or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.database, re.ASCII)
                is None
                or self.database
                in {"mysql", "information_schema", "performance_schema", "sys"}
            ):
                raise ValueError("Invalid connection identity")
            self.user.encode("utf8")
            self.tls_hostname.encode("ascii")
            space = EmbeddingSpace.model_validate(self.space.model_dump())
            identity = space.identity.encode("utf8")
            if (
                not 1 <= len(identity) <= 4096
                or len(space.identity) > 1024
                or "\0" in space.identity
                or space.dimensions > 16000
                or type(self.capacity) is not int
                or not 1 <= self.capacity <= 5000
                or self.capacity * space.dimensions * 8 > 64 * 1024 * 1024
            ):
                raise ValueError("Invalid binding bounds")
            object.__setattr__(self, "ca_file", Path(self.ca_file).absolute())
            object.__setattr__(self, "space", space)
            object.__setattr__(self, "ttl", resolve_ttl(None, self.ttl))
            object.__setattr__(self, "timeout", timeout(self.timeout))
            object.__setattr__(self, "close_timeout", timeout(self.close_timeout))
        except (ValueError, TypeError, AttributeError, OSError):
            safe(CacheConfigurationError("Invalid MySQL store configuration"))

    @property
    def descriptor(self) -> tuple[bytes, int, bytes, int, bytes | None]:
        identity = self.space.identity.encode("utf8")
        return (
            sha256(identity).digest(),
            self.space.dimensions,
            identity,
            self.capacity,
            None if self.ttl is None else self.ttl.hex().encode("ascii"),
        )
