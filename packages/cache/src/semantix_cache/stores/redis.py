"""Optional bounded exact Redis storage; schema initialization is explicit."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC as _UTC
from datetime import datetime
from datetime import timedelta as _timedelta
from hashlib import sha256
from importlib.metadata import version as _version
from types import TracebackType
from typing import NoReturn as _NoReturn
from typing import Self, cast
from urllib.parse import urlsplit

import numpy as np
from numpy.typing import NDArray

try:
    from redis.asyncio import ConnectionPool as _ConnectionPool
    from redis.asyncio import Redis
    from redis.asyncio.connection import Connection as _Connection
    from redis.asyncio.connection import DefaultParser as _DefaultParser
    from redis.asyncio.connection import SSLConnection as _SSLConnection
    from redis.asyncio.retry import Retry
    from redis.backoff import NoBackoff
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import InvalidResponse, ResponseError
    from redis.exceptions import TimeoutError as RedisTimeoutError
except ModuleNotFoundError as exc:
    if exc.name != "redis":
        raise
    raise ImportError("Redis storage requires 'semantix-cache[redis]'.") from None

from .._lifecycle import Lifecycle
from .._semantics import (
    cache_key_value,
    namespace_value,
    normalized_vector,
    resolve_ttl,
)
from .._semantics import finite_number as _finite_number
from .._semantics import nearest_index as _nearest_index
from ..errors import (
    CacheConfigurationError,
    CacheStoreError,
    CacheTimeoutError,
    CacheValidationError,
    SemantixCacheError,
)
from ..inspection import (
    InspectionEntry,
    InspectionPage,
    InspectionSort,
    inspection_arguments,
    inspection_namespaces,
)
from ..inspection import remaining as _remaining
from ..models import CacheEntry, CacheMatch, EmbeddingSpace
from ._backends.redis import config as _redis_config
from ._backends.redis import format as _redis_format
from ._backends.redis import scripts as _redis_scripts
from ._backends.redis.inspection import inspect_page as _inspect_page

# Preserve existing module bindings from their canonical owners.
UTC = _UTC
timedelta = _timedelta
version = _version
NoReturn = _NoReturn
ConnectionPool = _ConnectionPool
Connection = _Connection
DefaultParser = _DefaultParser
SSLConnection = _SSLConnection
finite_number = _finite_number
nearest_index = _nearest_index
remaining = _remaining
_client = _redis_config._client
_timeout = _redis_config._timeout
_raise_safe = _redis_format._raise_safe
_micros = _redis_format._micros
_score: Callable[
    [NDArray[np.float64], object, int, str], tuple[bytes, bytes, float] | None
] = _redis_format._score
_decode = _redis_format._decode
_datetime = _redis_format._datetime
_row = _redis_format._row
_unique_object = _redis_format._unique_object

_EPOCH = _redis_format._EPOCH
_PREFIX = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", re.ASCII)
_MARKER = "semantix-cache:redis:v1"


_SERVER_MINIMUM_PATCH = {
    (7, 4): 11,
    (8, 2): 10,
    (8, 4): 7,
    (8, 6): 7,
    (8, 8): 3,
    (8, 10): 2,
}


def _supported_server_version(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        major, minor, patch = (int(part) for part in value.split("."))
    except ValueError:
        return False
    minimum = _SERVER_MINIMUM_PATCH.get((major, minor))
    return (
        minimum is not None and patch >= minimum and value == f"{major}.{minor}.{patch}"
    )


@dataclass(frozen=True)
class _Configuration:
    space: EmbeddingSpace
    prefix: str
    capacity: int
    ttl: float | None
    timeout: float
    close_timeout: float

    def __post_init__(self) -> None:
        try:
            space = EmbeddingSpace.model_validate(self.space.model_dump())
            space.identity.encode("utf-8")
            if len(space.identity) > 1024 or "\0" in space.identity:
                raise ValueError("Invalid space")
            if (
                space.dimensions > 16000
                or isinstance(self.capacity, bool)
                or not isinstance(self.capacity, int)
                or not 1 <= self.capacity <= 5000
                or self.capacity * space.dimensions * 8 > 64 * 1024 * 1024
                or not isinstance(self.prefix, str)
                or _PREFIX.fullmatch(self.prefix) is None
            ):
                raise ValueError("Invalid bounds")
            object.__setattr__(self, "space", space)
            object.__setattr__(self, "ttl", resolve_ttl(None, self.ttl))
            object.__setattr__(self, "timeout", _timeout(self.timeout))
            object.__setattr__(self, "close_timeout", _timeout(self.close_timeout))
        except (ValueError, AttributeError):
            _raise_safe(CacheConfigurationError("Invalid Redis store configuration"))

    @property
    def keys(self) -> tuple[str, str, str]:
        identity = self.space.identity.encode("utf-8")
        digest = sha256(
            b"semantix-cache:redis:v1\0"
            + str(len(identity)).encode("ascii")
            + b":"
            + identity
            + b":"
            + str(self.space.dimensions).encode("ascii")
        ).hexdigest()
        base = self.prefix + ":{" + digest + "}:"
        return base + "meta", base + "entries", base + "lru"

    @property
    def descriptor(self) -> list[str]:
        return [
            _MARKER,
            _CHECKSUM,
            self.space.identity,
            str(self.space.dimensions),
            str(self.capacity),
            "" if self.ttl is None else self.ttl.hex(),
        ]


_COMMON = _redis_scripts._COMMON
_DATA = _redis_scripts._DATA
_READ = _redis_scripts._READ
_WRITE = _redis_scripts._WRITE
_INITIALIZE = _redis_scripts._INITIALIZE
_CHECKSUM = _redis_scripts._CHECKSUM
_CLEAR_ALL = _redis_scripts._CLEAR_ALL
_INSPECT = _redis_scripts._INSPECT


class RedisStore:
    """A CacheStore binding to three owned keys on a Redis primary.

    Construction borrows the client and does not initialize or adopt keys.
    The supported deployment is a direct writable standalone Redis Open Source
    primary in the supported 7.4/8.2/8.4/8.6/8.8/8.10 release families at
    verified patch floors, using noeviction; Cluster, Sentinel, replica reads
    and automatic failover are outside this boundary. Operators own persistence,
    backups and stable server time; Redis storage alone is no durability promise.

    Prefix, endpoint/database and exact space identity/dimensions select the
    binding's meta hash, entries hash and LRU sorted set. Its marked descriptor
    also checks script checksum, capacity and default TTL. Capacity spans all
    namespaces; namespace authorization belongs to the caller. Lua mutations
    atomically manage revisions, server-clock TTL and LRU. A dirty mutation
    marker fails closed and needs operator recovery, never automatic adoption.

    Operations include worker admission, I/O, scoring/decoding and acknowledgement
    within one deadline. Expected transport/response failures use safe typed
    errors without raw credentials or private payloads; programming errors and
    cancellation propagate. After dispatch, an unacknowledged mutation may have
    completed. There is no automatic replay, repair or fallback; inspect state
    before deciding whether a new write or hit is appropriate.
    """

    def __init__(
        self,
        *,
        client: Redis,
        embedding_space: EmbeddingSpace,
        key_prefix: str = "semantix_cache",
        max_size: int = 500,
        default_ttl_seconds: float | None = 3600.0,
        operation_timeout_seconds: float = 30.0,
        close_timeout_seconds: float = 30.0,
    ) -> None:
        """Bind a borrowed binary RESP2 client without network setup or key creation.

        The client/pool must keep its validated policy stable and remain
        caller-owned after store close or async context exit.

        Args:
            client: Standard redis.asyncio.Redis and ConnectionPool from redis-py
                7.4.1, 8.0.1 or 8.1.x, with positive finite socket deadlines,
                binary responses and async Retry(NoBackoff(), 0).
                Custom pools/parsers are unsupported.
            embedding_space: Stable identity (at most 1,024 characters, no NUL)
                and 1-16,000 dimensions for every entry in this binding.
            key_prefix: Application-owned prefix; default semantix_cache. Matches
                [A-Za-z0-9][A-Za-z0-9._:-]{0,127}; unrelated keys are never adopted.
            max_size: Binding-wide capacity, 1-5,000, default 500. The projection
                max_size * dimensions * 8 must fit 64 MiB; this is not an RSS limit.
            default_ttl_seconds: Positive finite retention up to 31,536,000 seconds,
                defaulting to 3,600. None permits writes without expiry.
            operation_timeout_seconds: Positive finite total deadline, at most
                86,400 seconds; defaults to 30.
            close_timeout_seconds: Owned cleanup deadline with the same bounds and
                default. Borrowed resources are never closed here.

        Raises:
            CacheConfigurationError: If the client policy or binding settings are invalid.
        """

        if not isinstance(cast(object, embedding_space), EmbeddingSpace):
            raise CacheConfigurationError("Invalid Redis embedding space")
        self._config = _Configuration(
            embedding_space,
            key_prefix,
            max_size,
            default_ttl_seconds,
            operation_timeout_seconds,
            close_timeout_seconds,
        )
        _client(client)
        self._client = client
        self._state = Lifecycle()
        self._owned = False
        self._cleanup: asyncio.Task[None] | None = None
        self._worker_slot = asyncio.Semaphore(1)
        self._workers: set[asyncio.Task[tuple[bytes, bytes, float] | None]] = set()

    @property
    def embedding_space(self) -> EmbeddingSpace:
        return self._config.space

    @property
    def default_ttl_seconds(self) -> float | None:
        return self._config.ttl

    @asynccontextmanager
    async def _operation(self) -> AsyncGenerator[None, None]:
        with self._state.operation():
            failure: SemantixCacheError | None = None
            try:
                loop = asyncio.get_running_loop()
                deadline = loop.time() + self._config.timeout
                async with asyncio.timeout_at(deadline):
                    yield
                    # Include final synchronous winner decoding in the deadline.
                    if loop.time() >= deadline:
                        raise TimeoutError
            except (TimeoutError, RedisTimeoutError):
                failure = CacheTimeoutError("Redis operation deadline expired")
            except (OSError, RedisConnectionError, InvalidResponse, ResponseError):
                failure = CacheStoreError(
                    "Redis operation failed; check connectivity, permissions and binding state"
                )
            if failure is not None:
                _raise_safe(failure)

    async def initialize_schema(self, *, initialization_client: Redis) -> None:
        """Explicitly create a fresh descriptor or validate the identical ready layout.

        Check supported server version/mode/primary role, noeviction and required
        commands before the atomic initialization script. Repeated/concurrent
        identical setup is safe. Partial, unmarked, mismatched or dirty bindings
        are rejected; this never changes Redis configuration or repairs data.

        Args:
            initialization_client: Borrowed client with separately authorized setup
                permissions, including INFO, CONFIG GET and COMMAND INFO. It must
                target the runtime binding's endpoint/database and obey the same
                client policy. The caller supplies and closes it.

        Raises:
            CacheConfigurationError: If the supplied client policy is unsupported.
            CacheStoreError: If deployment/layout checks or expected Redis calls fail.
            CacheTimeoutError: If the operation deadline expires.
        """

        self._state.check_open()
        _client(initialization_client)
        async with self._operation():
            execute = cast(
                Callable[..., Awaitable[object]],
                initialization_client.execute_command,  # pyright: ignore[reportUnknownMemberType]
            )
            server = cast(dict[str, object], await execute("INFO", "server"))
            replication = cast(dict[str, object], await execute("INFO", "replication"))
            cluster = cast(dict[str, object], await execute("INFO", "cluster"))
            policy = cast(
                dict[str, object], await execute("CONFIG GET", "maxmemory-policy")
            )
            if (
                not isinstance(server, dict)
                or not _supported_server_version(server.get("redis_version"))
                or server.get("server_name", "redis") != "redis"
                or "valkey_version" in server
                or server.get("redis_mode") != "standalone"
                or replication.get("role") != "master"
                or cluster.get("cluster_enabled") != 0
                or policy.get("maxmemory-policy") != "noeviction"
            ):
                raise CacheStoreError(
                    "Require Redis 7.4.11+, 8.2.10+, 8.4.7+, 8.6.7+, 8.8.3+ or "
                    "8.10.2+ within those release families, a direct writable "
                    "non-cluster primary and noeviction"
                )
            commands = await execute(
                "COMMAND", "INFO", "eval", "eval_ro", "hpexpireat", "hpexpiretime"
            )
            if (
                not isinstance(commands, dict)
                or set(cast(dict[object, object], commands))
                != {"eval", "eval_ro", "hpexpireat", "hpexpiretime"}
                or any(v is None for v in cast(dict[object, object], commands).values())
            ):
                raise CacheStoreError(
                    "Required Redis scripting/field-expiry commands are unavailable"
                )
            # redis-py 7.4 shares sync/async Lua annotations; this client is asynchronous.
            await cast(
                Awaitable[object],
                initialization_client.eval(
                    _INITIALIZE, 3, *self._config.keys, *self._config.descriptor
                ),
            )

    async def validate_schema(self) -> None:
        """Validate the existing marked binding using a read-only Lua call.

        Check descriptor/checksum, ready status, counters and entry metadata;
        this does not fully decode every payload/vector or repeat setup's server
        configuration probes. Ordinary use never initializes an absent binding.

        Raises:
            CacheStoreError: For absent, mismatched, corrupt or dirty binding state,
                or expected Redis failures.
            CacheTimeoutError: If the operation deadline expires.
        """

        async with self._operation():
            await cast(
                Awaitable[object],
                self._client.eval_ro(
                    _READ, 3, *self._config.keys, *self._config.descriptor, "validate"
                ),
            )

    async def _inspect(
        self,
        *,
        namespace: str | None,
        namespaces: tuple[str, ...] | None,
        cache_key: str | None,
        offset: int,
        limit: int,
        sort: InspectionSort,
    ) -> InspectionPage:
        return await _inspect_page(
            self._client,
            script=_INSPECT,
            keys=self._config.keys,
            descriptor=self._config.descriptor,
            namespace=namespace,
            namespaces=namespaces,
            cache_key=cache_key,
            offset=offset,
            limit=limit,
            sort=sort,
        )

    async def inspect_entries(
        self,
        *,
        namespace: str | None = None,
        offset: int = 0,
        limit: int = 20,
        search: str | None = None,
        sort: InspectionSort = "newest",
    ) -> InspectionPage:
        """Observe live metadata without hit/LRU mutations or explicit expiry cleanup.

        Read-only Lua scans scalar metadata and decodes only the selected page.
        Prompt search scans payloads in batches of 100 up to binding capacity,
        under one operation deadline; concurrent changes can shift offsets/totals
        even within a searched page. Sensitive previews require authorization.

        Args:
            namespace: Exact namespace, or None for all in this binding.
            offset: Nonnegative live offset, not a stable continuation token.
            limit: Page size from 1 through 100.
            search: Optional trimmed, casefolded prompt substring, at most 2,000
                characters. Blank text does not trigger a payload search.
            sort: newest, oldest, most_hit or nearest_expiry.

        Returns:
            Detached page with prompts and at most 240 response-preview characters,
            no vectors and response=None. TTL/counters are observations, not leases
            or durability promises; Redis native expiry may proceed independently.

        Raises:
            CacheValidationError: If inspection arguments are invalid.
        """

        async with self._operation():
            inspection_arguments(namespace, offset, limit, search, sort)
            needle = "" if search is None else search.strip().casefold()
            if not needle:
                return await self._inspect(
                    namespace=namespace,
                    namespaces=None,
                    cache_key=None,
                    offset=offset,
                    limit=limit,
                    sort=sort,
                )
            # Each 100-entry page revalidates and sorts binding metadata;
            # prompt search scans payloads up to the configured capacity.
            selected: list[InspectionEntry] = []
            matched = 0
            scanned = 0
            while scanned < self._config.capacity:
                page = await self._inspect(
                    namespace=namespace,
                    namespaces=None,
                    cache_key=None,
                    offset=scanned,
                    limit=100,
                    sort=sort,
                )
                for item in page.items:
                    if needle in item.prompt.casefold():
                        if offset <= matched < offset + limit:
                            selected.append(item)
                        matched += 1
                scanned += 100
                if not page.has_more:
                    break
            return InspectionPage(
                items=tuple(selected),
                total=matched,
                offset=offset,
                limit=limit,
                has_more=offset + len(selected) < matched,
            )

    async def inspect_entry(
        self, cache_key: str, *, namespaces: tuple[str, ...] | None
    ) -> InspectionEntry | None:
        """Observe a live entry and its sensitive full response using read-only Lua.

        Args:
            cache_key: Canonical key within this binding.
            namespaces: Caller-authorized tuple; () allows none, None allows all
                namespaces. This filter does not authenticate the caller.

        Returns:
            Detached detail or None if absent, expired or outside the scope.
            Observation neither confirms a hit nor extends TTL/promotes LRU.

        Raises:
            CacheValidationError: If the key or namespace scope is invalid.
        """

        async with self._operation():
            inspection_namespaces(namespaces)
            try:
                cache_key = cache_key_value(cache_key)
            except ValueError:
                _raise_safe(CacheValidationError("Invalid inspection key"))
            page = await self._inspect(
                namespace=None,
                namespaces=namespaces,
                cache_key=cache_key,
                offset=0,
                limit=1,
                sort="newest",
            )
            return page.items[0] if page.items else None

    async def clear_all(self) -> int:
        """Administratively clear members across this Redis binding's namespaces.

        Returns:
            Live removal count; expired members may also be cleaned. The descriptor
            and revision history remain. Caller authorization is required; this
            optional mutation does not flush the database or remove unrelated keys.
        """
        async with self._operation():
            result = await cast(
                Awaitable[object],
                self._client.eval(
                    _CLEAR_ALL,
                    3,
                    *self._config.keys,
                    *self._config.descriptor,
                    "clear",
                    "",
                ),
            )
            if type(result) is not int or result < 0:
                _raise_safe(CacheStoreError("Invalid Redis clear result"))
            return result

    async def aclose(self) -> None:
        """Seal an idle store and release only resources created by connect.

        Owned close shares one bounded, shielded cleanup task across concurrent
        and repeated calls. Caller cancellation propagates while cleanup continues;
        a later close observes that same result, including failure, without retry.
        Borrowed close only seals the wrapper. Persisted keys remain. Async context
        exit uses this path and propagates body exceptions when close succeeds.

        Raises:
            CacheBusyError: If admitted operations or retained numerical workers
                remain; admission stays open for draining and a later close.
            CacheTimeoutError: If owned cleanup exceeds the close deadline.
            CacheStoreError: For expected owned-client/pool cleanup failures.
        """

        if self._owned:
            await asyncio.shield(self._start_close())
        else:
            self._state.close(workers=bool(self._workers))

    async def put(self, entry: CacheEntry, *, ttl_seconds: float | None = None) -> None:
        """Write a normalized entry and enforce binding-wide LRU capacity with Lua.

        Allocate an increasing revision, reset hit metadata/expiry, remove expired
        members and evict least-recently-used overflow atomically. Deletion/clear
        retain revision history. A script failure after business writes can leave
        the binding dirty; later operations fail closed rather than repairing it.

        Args:
            entry: Valid CacheEntry from this space. Dimensions are checked;
                identity provenance remains the caller's responsibility.
            ttl_seconds: None inherits the default; a positive finite value up to
                31,536,000 seconds is capped by a finite default. Both values None
                mean no expiry. TTL starts at Redis TIME, is floored to whole
                microseconds (submicrosecond TTL expires immediately), and never
                slides on hits. Native field cleanup can lag logical expiry.

        Raises:
            CacheStoreError: If entry/TTL is invalid or expected Redis calls fail.
            CacheTimeoutError: If the operation deadline expires; a dispatched
                mutation may already have completed and is never replayed here.
        """

        async with self._operation():
            try:
                if not isinstance(cast(object, entry), CacheEntry):
                    raise TypeError("Invalid entry")
                entry = CacheEntry.model_validate(entry.model_dump())
                vector = normalized_vector(
                    entry.embedding, dimensions=self.embedding_space.dimensions
                )
                ttl = resolve_ttl(ttl_seconds, self.default_ttl_seconds)
                duration = ""
                if ttl is not None:
                    numerator, denominator = ttl.as_integer_ratio()
                    duration = str(numerator * 1000000 // denominator)
                payload = json.dumps(
                    {
                        "cache_key": entry.cache_key,
                        "namespace": entry.namespace,
                        "prompt": entry.prompt,
                        "response": entry.response,
                    },
                    ensure_ascii=True,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                requested = _micros(entry.created_at)
            except (ValueError, TypeError):
                _raise_safe(CacheStoreError("Invalid stored entry or TTL"))
            await cast(
                Awaitable[object],
                self._client.eval(
                    _WRITE,
                    3,
                    *self._config.keys,
                    *self._config.descriptor,
                    "put",
                    entry.namespace + "|" + entry.cache_key,
                    requested,
                    duration,
                    payload,
                    vector.astype("<f8", copy=False).tobytes(),
                ),
            )

    async def find_nearest(
        self, embedding: Sequence[float], *, namespace: str
    ) -> CacheMatch | None:
        """Score a bounded vector snapshot with exact client-side float64 cosine.

        A read-only script transfers all live vectors in the namespace without
        other prompts/responses. One admitted numerical worker scores them; only
        the winner payload is fetched under the expected revision. Search applies
        no threshold and changes neither hit metadata nor LRU. Cancellation or
        timeout leaves a started thread holding its slot until completion; close
        can remain busy after the caller has exited.

        Args:
            embedding: Finite, nonzero vector with the bound space's dimensions.
            namespace: Exact namespace to search; authorize it before calling.

        Returns:
            Detached validated candidate with score in [-1, 1], or None if empty
            or the winner expired/replaced/deleted before retrieval, without a
            rescan. Ties use ascending revision, then key. record_hit must still
            confirm the candidate; retrieval is not a lease.

        Raises:
            CacheValidationError: If vector or namespace is invalid.
            CacheStoreError: For corrupt eligible vectors/winner or expected Redis failures.
            CacheTimeoutError: If admission, I/O, scoring or decoding exceeds the deadline.
        """

        async with self._operation():
            try:
                namespace = namespace_value(namespace)
                query = normalized_vector(
                    embedding, dimensions=self.embedding_space.dimensions
                )
            except ValueError:
                _raise_safe(CacheValidationError("Invalid embedding or namespace"))
            await self._worker_slot.acquire()
            retained = False
            try:
                # O(N*D) vector transfer/scoring also needs validation and sorting;
                # choose an indexed backend only when measured workloads justify it.
                rows = await cast(
                    Awaitable[object],
                    self._client.eval_ro(
                        _READ,
                        3,
                        *self._config.keys,
                        *self._config.descriptor,
                        "snapshot",
                        namespace,
                    ),
                )
                worker = asyncio.create_task(
                    asyncio.to_thread(
                        _score, query, rows, self.embedding_space.dimensions, namespace
                    )
                )
                self._workers.add(worker)
                retained = True

                def completed(
                    task: asyncio.Task[tuple[bytes, bytes, float] | None],
                ) -> None:
                    self._workers.discard(task)
                    self._worker_slot.release()
                    if not task.cancelled():
                        task.exception()

                worker.add_done_callback(completed)
                winner = await asyncio.shield(worker)
            finally:
                if not retained:
                    self._worker_slot.release()
            if winner is None:
                return None
            member, revision, similarity = winner
            raw = await cast(
                Awaitable[object],
                self._client.eval_ro(
                    _READ,
                    3,
                    *self._config.keys,
                    *self._config.descriptor,
                    "winner",
                    member,
                    revision,
                ),
            )
            if raw is None:
                return None
            return _decode(raw, member, self.embedding_space.dimensions, similarity)

    def _member(self, cache_key: str, namespace: str) -> str:
        try:
            return namespace_value(namespace) + "|" + cache_key_value(cache_key)
        except ValueError:
            _raise_safe(CacheValidationError("Invalid cache key or namespace"))

    async def record_hit(
        self, cache_key: str, *, namespace: str, expected_created_at: datetime
    ) -> bool:
        """Atomically confirm a live revision and apply hit effects with Lua.

        Args:
            cache_key: Candidate key within the bound space.
            namespace: Exact candidate namespace.
            expected_created_at: Timezone-aware revision from the candidate entry.

        Returns:
            True after incrementing hit count, recording Redis server last access
            and promoting LRU. Revision/TTL stay unchanged. False rejects an absent,
            expired, foreign or replaced candidate without hit effects. A lost
            acknowledgement can follow a completed increment; no replay occurs.

        Raises:
            CacheValidationError: If key, namespace or revision is invalid.
        """

        async with self._operation():
            member = self._member(cache_key, namespace)
            try:
                revision = _micros(expected_created_at)
            except (ValueError, OverflowError):
                _raise_safe(
                    CacheValidationError("Expected revision must be timezone-aware")
                )
            result = await cast(
                Awaitable[object],
                self._client.eval(
                    _WRITE,
                    3,
                    *self._config.keys,
                    *self._config.descriptor,
                    "hit",
                    member,
                    revision,
                ),
            )
            return bool(result)

    async def delete_entry(self, cache_key: str, *, namespace: str) -> bool:
        """Remove only the given namespace/key member with an atomic Lua mutation.

        Returns:
            Whether it was live when removed. An expired member/tombstone can be
            cleaned while returning False. Binding revision history is retained.

        Raises:
            CacheValidationError: If the key or namespace is invalid.
        """

        async with self._operation():
            member = self._member(cache_key, namespace)
            return bool(
                await cast(
                    Awaitable[object],
                    self._client.eval(
                        _WRITE,
                        3,
                        *self._config.keys,
                        *self._config.descriptor,
                        "delete",
                        member,
                    ),
                )
            )

    async def clear(self, *, namespace: str) -> int:
        """Remove one namespace's members, retaining binding revision history.

        Returns:
            Number of live entries removed by Lua; expired members can also be
            cleaned without being counted. Other namespaces remain intact.

        Raises:
            CacheValidationError: If the namespace is invalid.
        """

        async with self._operation():
            try:
                namespace = namespace_value(namespace)
            except ValueError:
                _raise_safe(CacheValidationError("Invalid namespace"))
            result = await cast(
                Awaitable[object],
                self._client.eval(
                    _WRITE,
                    3,
                    *self._config.keys,
                    *self._config.descriptor,
                    "clear",
                    namespace,
                ),
            )
            return cast(int, result)

    @classmethod
    async def connect(
        cls,
        *,
        url: str,
        embedding_space: EmbeddingSpace,
        key_prefix: str = "semantix_cache",
        max_size: int = 500,
        default_ttl_seconds: float | None = 3600.0,
        max_connections: int = 5,
        connect_timeout_seconds: float = 10.0,
        operation_timeout_seconds: float = 30.0,
        close_timeout_seconds: float = 30.0,
    ) -> RedisStore:
        """Create an owned zero-retry client/pool and PING within a startup deadline.

        Binding/deadline arguments otherwise follow the constructor. This performs
        no initialization or schema validation; validate_schema checks an existing
        binding. Failed/cancelled PING starts bounded shielded cleanup before
        propagating the startup outcome; repeated cancellation can leave that
        cleanup finishing independently.

        Args:
            url: Private redis:// or rediss:// URL with endpoint and database path.
                Query parameters/fragments are rejected to prevent policy overrides.
            max_connections: Standard pool ceiling from 1 through 100, default 5.
            connect_timeout_seconds: Positive finite startup deadline, at most
                86,400 seconds, default 10; also sets socket-connect timeout.

        Returns:
            Store owning its client and pool; close with aclose or async context exit.

        Raises:
            CacheConfigurationError: If connection/binding settings are invalid.
            CacheTimeoutError: If startup or socket deadlines expire.
            CacheStoreError: For expected Redis connection failures.
        """

        failure: SemantixCacheError | None = None
        try:
            timeout = _timeout(connect_timeout_seconds)
            if not isinstance(url, str) or len(url) > 8192 or "\0" in url:
                raise ValueError("Invalid URL")
            parsed = urlsplit(url)
            if (
                parsed.scheme not in ("redis", "rediss")
                or not parsed.hostname
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Invalid URL")
            if (
                isinstance(max_connections, bool)
                or not isinstance(max_connections, int)
                or not 1 <= max_connections <= 100
            ):
                raise ValueError("Invalid pool bounds")
        except ValueError:
            _raise_safe(
                CacheConfigurationError("Invalid Redis connection configuration")
            )
        # Validate local settings before creating any network resources.
        _Configuration(
            embedding_space,
            key_prefix,
            max_size,
            default_ttl_seconds,
            operation_timeout_seconds,
            close_timeout_seconds,
        )
        active: Redis | None = None
        store: RedisStore | None = None
        try:
            # Verified redis-py releases leave **kwargs untyped; RedisStore validates policy.
            create = cast(Callable[..., Redis], Redis.from_url)  # pyright: ignore[reportUnknownMemberType]
            active = create(
                url,
                decode_responses=False,
                protocol=2,
                retry=Retry(NoBackoff(), 0),
                max_connections=max_connections,
                socket_connect_timeout=timeout,
                socket_timeout=_timeout(operation_timeout_seconds),
            )
            store = cls(
                client=active,
                embedding_space=embedding_space,
                key_prefix=key_prefix,
                max_size=max_size,
                default_ttl_seconds=default_ttl_seconds,
                operation_timeout_seconds=operation_timeout_seconds,
                close_timeout_seconds=close_timeout_seconds,
            )
            store._owned = True
            try:
                async with asyncio.timeout(timeout):
                    execute = cast(
                        Callable[..., Awaitable[object]],
                        active.execute_command,  # pyright: ignore[reportUnknownMemberType]
                    )
                    await execute("PING")
            except BaseException:
                # Cleanup only: programming failures and cancellation propagate.
                cleanup = store._start_close()
                # Preserve startup failure/cancellation after bounded cleanup.
                with suppress(SemantixCacheError):
                    await asyncio.shield(cleanup)
                raise
        except (TimeoutError, RedisTimeoutError):
            failure = CacheTimeoutError("Redis connection deadline expired")
        except ValueError:
            failure = CacheConfigurationError("Invalid Redis connection configuration")
        except (OSError, RedisConnectionError, InvalidResponse, ResponseError):
            failure = CacheStoreError(
                "Could not connect to the configured Redis primary"
            )
        if failure is not None:
            _raise_safe(failure)
        if store is None:
            raise RuntimeError("Unreachable Redis connection state")
        return store

    async def _close_owned(self) -> None:
        failure: SemantixCacheError | None = None
        try:
            async with asyncio.timeout(self._config.close_timeout):
                await self._client.aclose(close_connection_pool=True)
        except (TimeoutError, RedisTimeoutError):
            failure = CacheTimeoutError("Redis close deadline expired")
        except (OSError, RedisConnectionError, InvalidResponse, ResponseError):
            failure = CacheStoreError("Could not close owned Redis resources")
        if failure is not None:
            _raise_safe(failure)

    def _start_close(self) -> asyncio.Task[None]:
        if self._cleanup is None:
            self._state.close(workers=bool(self._workers))
            self._cleanup = asyncio.create_task(self._close_owned())
            self._cleanup.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        return self._cleanup

    async def __aenter__(self) -> Self:
        self._state.check_open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()
