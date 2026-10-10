"""Explicit Redis binding initialization; ordinary startup only validates.

The command owns a separate initialization client; RedisStore borrows it.
Metadata resolution does not construct providers, download models or run inference.
"""

import asyncio
import os
import sys

from redis.asyncio import Redis, from_url
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.exceptions import CacheStorageError
from app.providers.factory import create_default_provider_registry
from semantix_cache import EmbeddingSpace, SemantixCacheError
from semantix_cache.stores.redis import RedisStore


def _public_setup_failure(error: BaseException, *, cleanup: bool) -> BaseException:
    """Map declared package/Redis/OS/ValueError failures to fixed setup/cleanup errors.

    Return cancellation, programming errors and other BaseException values unchanged.
    This selector does not sanitize arbitrary exceptions or recursively rewrite groups.
    """
    if isinstance(error, (SemantixCacheError, RedisError, OSError, ValueError)):
        return CacheStorageError(
            "Redis setup cleanup failed"
            if cleanup
            else "Redis setup failed; verify initialization authority and binding configuration"
        )
    return error  # cancellation and programming errors retain their original identity


async def _close_setup_client(
    client: Redis, *, timeout_seconds: float, failure: BaseException | None
) -> BaseException | None:
    """Await one bounded owned-client close task while recording caller cancellation.

    Shield that task rather than creating a new close per cancellation. A cancelled
    close task is terminal. Caller cancellation replaces the pending failure value;
    expected close failure is selected only if none is pending. Unexpected close
    failure propagates alone or joins a pending failure in BaseExceptionGroup.
    Shielding is not a guarantee of successful cleanup or a fixed final error under
    repeated cancellation. The caller interprets the returned failure.
    """

    async def close() -> None:
        async with asyncio.timeout(timeout_seconds):
            await client.aclose(close_connection_pool=True)

    cleanup = asyncio.create_task(close())
    while True:
        try:
            await asyncio.shield(cleanup)
            break
        except asyncio.CancelledError as error:
            # Caller cancellation waits for the single bounded close. A cancelled
            # close task is terminal; repeatedly shielding it would spin forever.
            failure = error
            if cleanup.done():
                break
        except (SemantixCacheError, RedisError, OSError, ValueError) as error:
            if failure is None:
                failure = _public_setup_failure(error, cleanup=True)
            break
        except BaseException as error:
            if failure is None:
                raise
            raise BaseExceptionGroup(
                "Redis setup and cleanup failed",
                [_public_setup_failure(failure, cleanup=False), error],
            ) from None
    return failure


async def initialize_redis(settings: Settings, *, initialization_url: str) -> None:
    """Initialize the configured binding with a separately authorized, owned client.

    Resolve built-in registry selection metadata without building providers; both
    selected capabilities must resolve. Use the embedding identity/dimensions to
    construct a borrowed-client RedisStore with configured prefix, capacity, TTL and
    deadlines. The client uses binary responses, protocol 2 and zero retries.
    The supplied initialization URL must target the intended runtime binding.

    Finally close any constructed store, then its owned client even after partial
    initialization. Store closure does not close this borrowed client. Expected
    cleanup errors preserve a pending failure; unexpected cleanup errors can form
    BaseExceptionGroup. Client-close cancellation can take priority over setup errors.
    Declared final failures are translated outside handlers with suppressed cause;
    cancellation/programming/group errors are not all converted to CacheStorageError.
    Cleanup does not roll back remote initialization or guarantee resource release.

    Args:
        settings: Validated Redis binding and built-in provider-selection settings.
        initialization_url: Private setup connection URL with initialization authority.
    """
    active: Redis | None = None
    store: RedisStore | None = None
    failure: BaseException | None = None
    try:
        metadata = (
            create_default_provider_registry(settings)
            .resolve(settings.embedding_provider, settings.generation_provider)
            .embedding_metadata
        )
        active = from_url(
            initialization_url,
            decode_responses=False,
            protocol=2,
            retry=Retry(NoBackoff(), 0),
            socket_timeout=settings.redis_operation_timeout_seconds,
            socket_connect_timeout=settings.redis_operation_timeout_seconds,
        )
        store = RedisStore(
            client=active,
            embedding_space=EmbeddingSpace(
                identity=metadata.space, dimensions=metadata.dimensions
            ),
            key_prefix=settings.redis_key_prefix,
            max_size=settings.max_cache_size,
            default_ttl_seconds=settings.cache_ttl_seconds,
            operation_timeout_seconds=settings.redis_operation_timeout_seconds,
            close_timeout_seconds=settings.redis_close_timeout_seconds,
        )
        await store.initialize_schema(initialization_client=active)
    except (
        SemantixCacheError,
        RedisError,
        OSError,
        ValueError,
        asyncio.CancelledError,
    ) as error:
        failure = error
    finally:
        # An unexpected in-flight error must survive an expected cleanup failure.
        if failure is None:
            failure = sys.exception()
        try:
            if store is not None:
                await store.aclose()  # borrowed client remains owned by this command
        except (SemantixCacheError, RedisError, OSError, ValueError) as error:
            if failure is None:
                failure = _public_setup_failure(error, cleanup=True)
        except BaseException as error:
            if failure is None:
                raise
            raise BaseExceptionGroup(
                "Redis setup and cleanup failed",
                [_public_setup_failure(failure, cleanup=False), error],
            ) from None
        finally:
            # Preserve an unexpected store-close failure while closing its owner.
            if sys.exception() is not None:
                failure = sys.exception()
            if active is not None:
                failure = await _close_setup_client(
                    active,
                    timeout_seconds=settings.redis_close_timeout_seconds,
                    failure=failure,
                )
    # Translate outside the handlers, leaving no raw exception in the public chain.
    # The original failure remains local for diagnosis until this boundary.
    if failure is not None:
        raise _public_setup_failure(failure, cleanup=False) from None


async def run() -> None:
    """Read setup configuration and require Redis plus REDIS_INITIALIZATION_URL.

    Settings validation happens first. This entrypoint then rejects a non-Redis
    backend or missing/empty initialization URL and delegates owned cleanup to
    initialize_redis. Running this module invokes the coroutine with asyncio.run.
    """
    settings = Settings()  # pyright: ignore[reportCallIssue] - environment supplies required fields
    if settings.cache_backend != "redis":
        raise CacheStorageError("Redis setup requires CACHE_BACKEND=redis")
    url = os.environ.get("REDIS_INITIALIZATION_URL")
    if not url:
        raise CacheStorageError(
            "REDIS_INITIALIZATION_URL is required for explicit setup"
        )
    await initialize_redis(settings, initialization_url=url)


if __name__ == "__main__":
    asyncio.run(run())
