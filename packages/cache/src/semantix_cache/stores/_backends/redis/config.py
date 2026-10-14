"""Stateless Redis client and timeout policy; no allocation or lifecycle state."""

from __future__ import annotations

import re
from importlib.metadata import version

from redis.asyncio import ConnectionPool, Redis
from redis.asyncio.connection import Connection, DefaultParser, SSLConnection
from redis.asyncio.retry import Retry

from ...._semantics import finite_number
from ....errors import CacheConfigurationError


def _timeout(value: float) -> float:
    result = finite_number(value, minimum=0.0, maximum=86400.0)
    if result == 0:
        raise ValueError("Timeout must be positive")
    return result


def _client(value: Redis) -> None:
    failure = False
    try:
        if (
            type(value) is not Redis
            or type(value.connection_pool) is not ConnectionPool
        ):
            raise ValueError("Unsupported client/pool")
        if re.fullmatch(r"8\.1\.\d+", version("redis")) is None:
            raise ValueError("Unsupported redis-py version")
        pool = value.connection_pool
        options = pool.connection_kwargs
        if pool.connection_class not in (Connection, SSLConnection):
            raise ValueError("Unsupported connection")
        retry = value.get_retry()
        if (
            type(retry) is not Retry
            or retry.get_retries() != 0
            or options.get("decode_responses", False) is not False
            or options.get("protocol", 2) != 2
            or options.get("redis_connect_func") is not None
            or options.get("parser_class", DefaultParser) is not DefaultParser
        ):
            raise ValueError("Unsupported client policy")
        _timeout(options["socket_timeout"])
        _timeout(options["socket_connect_timeout"])
    except (ValueError, KeyError, TypeError):
        failure = True
    if failure:
        raise CacheConfigurationError(
            "Use a binary RESP2 redis.asyncio.Redis with a standard pool, "
            "finite socket deadlines and redis.asyncio.retry.Retry(NoBackoff(), 0)"
        )
