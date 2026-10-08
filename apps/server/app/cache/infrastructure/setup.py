"""Explicit Redis binding initialization; ordinary startup only validates."""

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
