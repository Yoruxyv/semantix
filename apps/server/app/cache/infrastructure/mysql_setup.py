"""Operator-only MySQL setup; normal application startup never initializes storage."""

import asyncio
import os

from pydantic import SecretStr

from app.core.config import Settings
from app.core.exceptions import CacheStorageError
from app.providers.factory import create_default_provider_registry
from app.providers.registry import EmbeddingMetadata
from semantix_cache import EmbeddingSpace, SemantixCacheError
from semantix_cache.stores.mysql import MySQLStore


async def initialize_mysql(
    settings: Settings,
    *,
    metadata: EmbeddingMetadata,
    setup_user: SecretStr,
    setup_password: SecretStr,
) -> None:
    """Initialize only with explicit setup credentials and resolved metadata.

    The operator provisions the dedicated database, locked verifier account and
    grants separately. The package owns construction/disposal, including its
    public failed-construction cleanup diagnostics. Failure never authorizes an
    automatic setup retry, schema repair or a successful-cleanup claim.
    """
    if settings.cache_backend != "mysql":
        raise CacheStorageError("MySQL setup requires CACHE_BACKEND=mysql")
    if (
        not setup_user.get_secret_value().strip()
        or not setup_password.get_secret_value()
    ):
        raise CacheStorageError("Separate MySQL setup credentials are required")

    secrets = (
        settings.cache_mysql_address,
        settings.cache_mysql_tls_hostname,
        settings.cache_mysql_ca_file,
        settings.cache_mysql_database,
    )
    if any(value is None for value in secrets):
        raise CacheStorageError("MySQL configuration is incomplete")
    address, hostname, ca_file, database = (
        value.get_secret_value() for value in secrets if value is not None
    )
    try:
        await MySQLStore.initialize_schema(
            address=address,
            port=settings.cache_mysql_port,
            tls_hostname=hostname,
            ca_file=ca_file,
            database=database,
            user=setup_user.get_secret_value(),
            password=setup_password.get_secret_value(),
            embedding_space=EmbeddingSpace(
                identity=metadata.space, dimensions=metadata.dimensions
            ),
            max_size=settings.max_cache_size,
            default_ttl_seconds=settings.cache_ttl_seconds,
            operation_timeout_seconds=settings.cache_mysql_operation_timeout_seconds,
        )
    except SemantixCacheError:
        raise CacheStorageError(
            "MySQL setup failed; verify setup authority, storage and binding "
            "configuration; inspect public failed-construction cleanup diagnostics"
        ) from None


async def run() -> None:
    settings = Settings()  # pyright: ignore[reportCallIssue] - environment supplies required fields
    user = os.environ.get("CACHE_MYSQL_SETUP_USER")
    password = os.environ.get("CACHE_MYSQL_SETUP_PASSWORD")
    if not user or not password:
        raise CacheStorageError(
            "CACHE_MYSQL_SETUP_USER and CACHE_MYSQL_SETUP_PASSWORD are required"
        )
    metadata = (
        create_default_provider_registry(settings)
        .resolve(settings.embedding_provider, settings.generation_provider)
        .embedding_metadata
    )
    await initialize_mysql(
        settings,
        metadata=metadata,
        setup_user=SecretStr(user),
        setup_password=SecretStr(password),
    )


if __name__ == "__main__":
    asyncio.run(run())
