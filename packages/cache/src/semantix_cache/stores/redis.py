"""Optional bounded exact Redis storage; schema initialization is explicit."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from importlib.metadata import version
from types import TracebackType
from typing import NoReturn, Self, cast
from urllib.parse import urlsplit

import numpy as np
from numpy.typing import NDArray

try:
    from redis.asyncio import ConnectionPool, Redis
    from redis.asyncio.connection import Connection, DefaultParser, SSLConnection
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
    finite_number,
    namespace_value,
    nearest_index,
    normalized_vector,
    resolve_ttl,
)
from ..errors import (
    CacheConfigurationError,
    CacheStoreError,
    CacheTimeoutError,
    CacheValidationError,
    SemantixCacheError,
)
from ..models import CacheEntry, CacheMatch, EmbeddingSpace

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_PREFIX = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", re.ASCII)
_MARKER = "semantix-cache:redis:v1"


def _raise_safe(error: SemantixCacheError) -> NoReturn:
    # asynccontextmanager throws the raw body exception back into the generator.
    # Clear implicit chaining after the raise; bare re-raise preserves this chain.
    try:
        raise error from RuntimeError(str(error))
    except SemantixCacheError:
        error.__context__ = None
        raise


def _micros(value: datetime) -> str:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("Expected an aware datetime")
    delta = value.astimezone(UTC) - _EPOCH
    return str((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds)


def _datetime(value: bytes) -> datetime:
    return _EPOCH + timedelta(microseconds=int(value))


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


_COMMON = """
local meta, entries, lru = KEYS[1], KEYS[2], KEYS[3]
local names = {'marker','checksum','identity','dimensions','capacity','default_ttl'}
local function fail() error('Invalid Redis cache binding', 0) end
local function types()
    local expected = {'hash','hash','zset'}
    for i=1,3 do
        local t = redis.call('TYPE', KEYS[i]).ok
        if t ~= 'none' and t ~= expected[i] then fail() end
        if redis.call('PTTL', KEYS[i]) >= 0 then fail() end
    end
end
local function schema()
    types()
    if redis.call('HLEN',meta)~=9 then fail() end
    for i,name in ipairs(names) do
        if redis.call('HGET', meta, name) ~= ARGV[i] then fail() end
    end
    if redis.call('HGET', meta, 'status') ~= 'ready' then fail() end
    if redis.call('ZCARD', lru) > tonumber(ARGV[5]) then fail() end
end
"""

_DATA = """
local function uint(s)
    if type(s) ~= 'string' or not string.match(s, '^%d+$') or
       (#s > 1 and string.sub(s,1,1) == '0') then fail() end
    return s
end
local function cmp(a,b)
    local an,bn = string.sub(a,1,1)=='-',string.sub(b,1,1)=='-'
    if an ~= bn then return an and -1 or 1 end
    local aa,bb = an and string.sub(a,2) or a,bn and string.sub(b,2) or b
    local c = 0
    if #aa ~= #bb then c = #aa < #bb and -1 or 1
    elseif aa ~= bb then c = aa < bb and -1 or 1 end
    return an and -c or c
end
local function revision(s)
    if type(s) ~= 'string' or s == '-0' then fail() end
    uint(string.sub(s,1,1)=='-' and string.sub(s,2) or s)
    if cmp(s,'-62135596800000000') < 0 or cmp(s,'253402300799999999') > 0 then fail() end
    return s
end
local function add(a,b)
    uint(a); uint(b)
    local out,carry = '',0
    local i,j = #a,#b
    while i>0 or j>0 or carry>0 do
        local x = i>0 and tonumber(string.sub(a,i,i)) or 0
        local y = j>0 and tonumber(string.sub(b,j,j)) or 0
        local sum = x+y+carry
        out = tostring(sum%10)..out
        carry = math.floor(sum/10)
        i=i-1; j=j-1
    end
    return out
end
local function clock()
    local t = redis.call('TIME')
    return t[1]..string.rep('0',6-#t[2])..t[2]
end
local function millis(e)
    local ms = string.sub(e,1,#e-3)
    if string.sub(e,-3) ~= '000' then ms=add(ms,'1') end
    return ms
end
local function member(m)
    local ns,key = string.match(m,'^([^|]+)|([a-f0-9]+)$')
    if not ns or #ns>64 or not string.match(ns,'^[A-Za-z0-9][A-Za-z0-9._:-]*$') or #key~=64 then fail() end
    return ns,key
end
local function fields(m)
    return {m..':p',m..':v',m..':r',m..':e',m..':h',m..':a'}
end
local function item(m,now)
    member(m)
    local values = redis.call('HMGET',entries,m..':r',m..':e',m..':h',m..':a')
    local r,e,h,a = values[1],values[2],values[3],values[4]
    if e and e~='' then
        uint(e); revision(e)
        if cmp(e,now)<=0 then return nil end
    end
    if not r and not e and not h and not a then
        if redis.call('HEXISTS',entries,m..':p')~=0 or redis.call('HEXISTS',entries,m..':v')~=0 then fail() end
        return nil
    end
    revision(r)
    if not e or not h or not a then fail() end
    uint(h)
    if cmp(h,'9223372036854775807')>0 then fail() end
    if a~='' then uint(a); revision(a) end
    if redis.call('HSTRLEN',entries,m..':v')~=tonumber(ARGV[4])*8 or
       redis.call('HSTRLEN',entries,m..':p')<2 or
       redis.call('HSTRLEN',entries,m..':p')>1230000 then fail() end
    return values
end
local function state()
    schema()
    local last=redis.call('HGET',meta,'last_revision_us')
    if not last then fail() end
    if last~='' then revision(last) end
    local count=uint(redis.call('HGET',meta,'access_counter'))
    if cmp(count,'9007199254740991')>0 then fail() end
    if redis.call('HLEN',entries)>tonumber(ARGV[5])*6 then fail() end
    for _,field in ipairs(redis.call('HKEYS',entries)) do
        local m=string.match(field,'^(.*):[pvreha]$')
        if not m or not redis.call('ZSCORE',lru,m) then fail() end
        member(m)
    end
    return last,tonumber(count)
end
local function members()
    local ranked=redis.call('ZRANGE',lru,0,-1,'WITHSCORES')
    local result,prior={},0
    local count=tonumber(redis.call('HGET',meta,'access_counter'))
    for i=1,#ranked,2 do
        local score=tonumber(ranked[i+1])
        if not score or score<=prior or score>count or score%1~=0 then fail() end
        prior=score
        member(ranked[i])
        result[#result+1]=ranked[i]
    end
    return result
end
"""

_READ = (
    _COMMON
    + _DATA
    + """
state()
local now=clock()
local op=ARGV[7]
if op=='validate' then
    for _,m in ipairs(members()) do item(m,now) end
    return 1
end
if op=='snapshot' then
    local result={}
    for _,m in ipairs(members()) do
        if member(m)==ARGV[8] then
            local values=item(m,now)
            if values then
                result[#result+1]={m,values[1],values[2],redis.call('HGET',entries,m..':v')}
            end
        end
    end
    return result
end
if op=='winner' then
    local m=ARGV[8]
    local values=item(m,now)
    if not values or values[1]~=ARGV[9] then return false end
    if not redis.call('ZSCORE',lru,m) then fail() end
    return {redis.call('HGET',entries,m..':p'),redis.call('HGET',entries,m..':v'),values[1],values[2]}
end
fail()
"""
)

_WRITE = (
    _COMMON
    + _DATA
    + """
local last,count=state()
local ranked=members()
local now=clock()
local op,m=ARGV[7],ARGV[8]
local current,all,expired={}, {}, {}
if op=='put' or op=='clear' then
    all=ranked
    for _,key in ipairs(all) do
        current[key]=item(key,now)
        if not current[key] then expired[#expired+1]=key end
    end
elseif op=='hit' or op=='delete' then
    current[m]=item(m,now)
    if current[m] and not redis.call('ZSCORE',lru,m) then fail() end
else fail() end
if op=='hit' then
    if not current[m] or current[m][1]~=ARGV[9] then return 0 end
    if current[m][3]=='9223372036854775807' then fail() end
end
local expiry=''
if op=='put' then
    member(m)
    revision(ARGV[9])
    if last=='253402300799999999' then fail() end
    if ARGV[10]~='' then expiry=add(now,uint(ARGV[10])); revision(expiry) end
    if #ARGV[11]<2 or #ARGV[11]>1230000 or #ARGV[12]~=tonumber(ARGV[4])*8 then fail() end
end
local function permit(command,key,...)
    if not redis.acl_check_cmd(command,key,...) then fail() end
end
permit('HSET',meta,'status','mutating')
permit('HDEL',entries,'preflight')
permit('ZREM',lru,'preflight')
if op=='put' or op=='hit' then
    permit('HSET',meta,'access_counter','1')
    permit('ZADD',lru,'1',m)
    permit('HSET',entries,m..':a',now)
    if op=='put' then
        permit('HINCRBY',meta,'last_revision_us',1)
        permit('HSET',entries,m..':p',ARGV[11])
    else permit('HINCRBY',entries,m..':h',1) end
    local e=op=='put' and expiry or current[m][2]
    if e~='' then permit('HPEXPIREAT',entries,millis(e),'FIELDS',1,m..':a') end
end
redis.call('HSET',meta,'status','mutating')
local function remove(key)
    redis.call('HDEL',entries,unpack(fields(key)))
    redis.call('ZREM',lru,key)
end
local function rank()
    if count>=9007199254740990 then
        local ordered=redis.call('ZRANGE',lru,0,-1)
        for i,key in ipairs(ordered) do redis.call('ZADD',lru,i,key) end
        count=#ordered
    end
    count=count+1
    redis.call('HSET',meta,'access_counter',string.format('%.0f',count))
    return count
end
local result=0
if op=='put' then
    for _,key in ipairs(expired) do remove(key) end
    local r=ARGV[9]
    if last~='' and cmp(r,last)<=0 then
        redis.call('HINCRBY',meta,'last_revision_us',1)
        r=redis.call('HGET',meta,'last_revision_us')
    else redis.call('HSET',meta,'last_revision_us',r) end
    redis.call('HSET',entries,m..':p',ARGV[11],m..':v',ARGV[12],m..':r',r,m..':e',expiry,m..':h','0',m..':a','')
    redis.call('ZADD',lru,rank(),m)
    if expiry~='' then
        redis.call('HPEXPIREAT',entries,millis(expiry),'FIELDS',6,unpack(fields(m)))
        if cmp(expiry,now)<=0 then remove(m) end
    end
    while redis.call('ZCARD',lru)>tonumber(ARGV[5]) do
        remove(redis.call('ZRANGE',lru,0,0)[1])
    end
elseif op=='hit' then
    redis.call('HINCRBY',entries,m..':h',1)
    redis.call('HSET',entries,m..':a',now)
    redis.call('ZADD',lru,rank(),m)
    local e=current[m][2]
    if e~='' then redis.call('HPEXPIREAT',entries,millis(e),'FIELDS',1,m..':a') end
    result=1
elseif op=='delete' then
    result=current[m] and 1 or 0
    remove(m)
elseif op=='clear' then
    for _,key in ipairs(all) do
        if member(key)==m then
            if current[key] then result=result+1 end
            remove(key)
        end
    end
end
redis.call('HSET',meta,'status','ready')
return result
"""
)

_INITIALIZE = (
    _COMMON
    + _DATA
    + """
types()
if redis.call('EXISTS',meta)==1 then
    state()
    local now=clock()
    for _,m in ipairs(members()) do item(m,now) end
    return 0
end
if redis.call('EXISTS',entries,lru)~=0 then fail() end
local fields={}
for i,name in ipairs(names) do fields[#fields+1]=name; fields[#fields+1]=ARGV[i] end
fields[#fields+1]='last_revision_us'; fields[#fields+1]=''
fields[#fields+1]='access_counter'; fields[#fields+1]='0'
fields[#fields+1]='status'; fields[#fields+1]='ready'
redis.call('HSET',meta,unpack(fields))
return 1
"""
)

_CHECKSUM = sha256((_INITIALIZE + _READ + _WRITE).encode()).hexdigest()


def _row(raw: object) -> tuple[bytes, bytes, bytes, bytes]:
    if not isinstance(raw, list):
        raise TypeError("Invalid Redis response row")
    parts = cast(list[object], raw)
    if len(parts) != 4 or not all(isinstance(part, bytes) for part in parts):
        raise ValueError("Invalid Redis response row")
    return cast(tuple[bytes, bytes, bytes, bytes], tuple(parts))


def _score(
    query: NDArray[np.float64], rows: object, dimensions: int, namespace: str
) -> tuple[bytes, bytes, float] | None:
    try:
        if not isinstance(rows, list):
            raise TypeError("Invalid snapshot")
        candidates: list[tuple[int, str, bytes, bytes, NDArray[np.float64]]] = []
        for row in cast(list[object], rows):
            member, revision, expiry, blob = _row(row)
            scope, key = member.decode("ascii").split("|")
            if namespace_value(scope) != namespace:
                raise ValueError("Invalid snapshot scope")
            cache_key_value(key)
            _datetime(revision)
            if expiry:
                _datetime(expiry)
            if len(blob) != dimensions * 8:
                raise ValueError("Invalid stored vector")
            vector = np.frombuffer(blob, dtype="<f8")
            candidates.append((int(revision), key, member, revision, vector))
        candidates.sort(key=lambda row: (row[0], row[1]))
        if not candidates:
            return None
        vectors = cast(Sequence[Sequence[float]], [row[4] for row in candidates])
        # Packed <f8 already guarantees numeric component types and dimensions.
        # Validate finite magnitudes with NumPy, then reuse the shared cosine kernel.
        matrix = np.asarray(vectors, dtype=np.float64)
        with np.errstate(over="ignore", invalid="ignore"):
            valid = (
                np.isfinite(matrix).all()
                and np.isfinite(np.linalg.norm(matrix, axis=1)).all()
            )
        if not valid:
            raise ValueError("Invalid stored vector magnitude")
        index, similarity = nearest_index(
            query, cast(Sequence[Sequence[float]], matrix)
        )
        return candidates[index][2], candidates[index][3], similarity
    except (ValueError, TypeError, OverflowError):
        _raise_safe(CacheStoreError("Invalid stored Redis vector snapshot"))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate payload key")
        result[key] = value
    return result


def _decode(
    raw: object, member: bytes, dimensions: int, similarity: float
) -> CacheMatch:
    try:
        payload, blob, revision, expiry = _row(raw)
        try:
            values: object = json.loads(
                payload.decode("utf-8"), object_pairs_hook=_unique_object
            )
        except RecursionError:
            _raise_safe(CacheStoreError("Invalid stored Redis winner"))
        if not isinstance(values, dict):
            raise TypeError("Invalid payload")
        data = cast(dict[object, object], values)
        if set(data) != {"cache_key", "namespace", "prompt", "response"} or not all(
            isinstance(v, str) for v in data.values()
        ):
            raise ValueError("Invalid payload")
        strings = cast(dict[str, str], data)
        scope, key = member.decode("ascii").split("|")
        if strings["namespace"] != scope or strings["cache_key"] != key:
            raise ValueError("Invalid payload scope")
        if len(blob) != dimensions * 8:
            raise ValueError("Invalid stored vector")
        vector = np.frombuffer(blob, dtype="<f8")
        normalized_vector(cast(Sequence[float], vector), dimensions=dimensions)
        entry = CacheEntry(
            cache_key=strings["cache_key"],
            namespace=strings["namespace"],
            prompt=strings["prompt"],
            response=strings["response"],
            embedding=tuple(float(v) for v in vector),
            created_at=_datetime(revision),
        )
        return CacheMatch(
            entry=entry,
            similarity_score=similarity,
            expires_at=None if not expiry else _datetime(expiry),
        )
    except (ValueError, TypeError, OverflowError):
        _raise_safe(CacheStoreError("Invalid stored Redis winner"))


class RedisStore:
    """A CacheStore binding to three owned keys on a Redis primary.

    Construction borrows the client and does not initialize or adopt keys.
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
                re.fullmatch(
                    r"8\.10\.(?:[2-9]|[1-9][0-9]+)", str(server.get("redis_version"))
                )
                is None
                or server.get("redis_mode") != "standalone"
                or replication.get("role") != "master"
                or cluster.get("cluster_enabled") != 0
                or policy.get("maxmemory-policy") != "noeviction"
            ):
                raise CacheStoreError(
                    "Require Redis Open Source >=8.10.2,<8.11, a direct writable "
                    "non-cluster primary and noeviction"
                )
            commands = await execute(
                "COMMAND", "INFO", "eval", "eval_ro", "hpexpireat", "hpexpiretime"
            )
            if (
                not isinstance(commands, dict)
                or len(cast(dict[object, object], commands)) != 4
                or any(v is None for v in cast(dict[object, object], commands).values())
            ):
                raise CacheStoreError(
                    "Required Redis scripting/field-expiry commands are unavailable"
                )
            await initialization_client.eval(
                _INITIALIZE, 3, *self._config.keys, *self._config.descriptor
            )

    async def validate_schema(self) -> None:
        async with self._operation():
            await self._client.eval_ro(
                _READ, 3, *self._config.keys, *self._config.descriptor, "validate"
            )

    async def aclose(self) -> None:
        if self._owned:
            await asyncio.shield(self._start_close())
        else:
            self._state.close(workers=bool(self._workers))

    async def put(self, entry: CacheEntry, *, ttl_seconds: float | None = None) -> None:
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
            await self._client.eval(
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
            )

    async def find_nearest(
        self, embedding: Sequence[float], *, namespace: str
    ) -> CacheMatch | None:
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
                # ponytail: bounded O(N) Lua and O(N*D) transfer/scoring; consider
                # an indexed backend only when measured workloads exceed this ceiling.
                rows = await self._client.eval_ro(
                    _READ,
                    3,
                    *self._config.keys,
                    *self._config.descriptor,
                    "snapshot",
                    namespace,
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
            raw = await self._client.eval_ro(
                _READ,
                3,
                *self._config.keys,
                *self._config.descriptor,
                "winner",
                member,
                revision,
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
        async with self._operation():
            member = self._member(cache_key, namespace)
            try:
                revision = _micros(expected_created_at)
            except (ValueError, OverflowError):
                _raise_safe(
                    CacheValidationError("Expected revision must be timezone-aware")
                )
            result = await self._client.eval(
                _WRITE,
                3,
                *self._config.keys,
                *self._config.descriptor,
                "hit",
                member,
                revision,
            )
            return bool(result)

    async def delete_entry(self, cache_key: str, *, namespace: str) -> bool:
        async with self._operation():
            member = self._member(cache_key, namespace)
            return bool(
                await self._client.eval(
                    _WRITE,
                    3,
                    *self._config.keys,
                    *self._config.descriptor,
                    "delete",
                    member,
                )
            )

    async def clear(self, *, namespace: str) -> int:
        async with self._operation():
            try:
                namespace = namespace_value(namespace)
            except ValueError:
                _raise_safe(CacheValidationError("Invalid namespace"))
            result = await self._client.eval(
                _WRITE,
                3,
                *self._config.keys,
                *self._config.descriptor,
                "clear",
                namespace,
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
            # Pinned redis-py 8.1 leaves **kwargs untyped; RedisStore validates policy.
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
