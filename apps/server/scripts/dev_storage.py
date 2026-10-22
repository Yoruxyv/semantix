"""Development-only setup/validation job; never imported by server runtime."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from typing import cast
from urllib.parse import unquote, urlsplit

import asyncpg

from app.benchmark.infrastructure import database as evaluation_database
from app.cache.infrastructure.setup import initialize_redis
from app.core.config import Settings, get_settings
from app.infrastructure import coordination_database, migrate
from app.providers.factory import create_default_provider_registry
from semantix_cache import EmbeddingSpace
from semantix_cache.stores.pgvector import PgVectorStore
from semantix_cache.stores.redis import RedisStore


def plan(settings: Settings) -> dict[str, bool]:
    """Validate additional launcher boundaries without network or provider calls."""
    unsupported = {
        "sqlite": "SQLite requires a single-process native server on trusted local disk; Compose is unsupported",
        "mysql": "MySQL requires explicit operator setup and validated native startup; development Compose is not certified",
    }.get(settings.cache_backend)
    if unsupported is not None:
        raise ValueError(unsupported)
    if any(
        os.environ.get(name)
        for name in (
            "MIGRATION_DATABASE_URL",
            "DATABASE_RUNTIME_ROLE",
            "REDIS_INITIALIZATION_URL",
            "POSTGRES_PASSWORD",
        )
    ):
        raise ValueError("Operator credentials must be supplied separately")
    provider_secrets = {
        "huggingface": settings.hf_api_key,
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "gemini": settings.gemini_api_key,
    }
    for provider in {settings.embedding_provider, settings.generation_provider}:
        secret = provider_secrets.get(provider)
        if secret is not None and secret.get_secret_value().startswith("replace-"):
            raise ValueError("Replace selected provider credentials or select mock")
    pg_local = False
    if settings.database_required:
        parsed = urlsplit(settings.database_dsn)
        if (
            not parsed.username
            or not parsed.password
            or parsed.hostname is None
            or parsed.hostname.endswith(".invalid")
            or "replace-" in unquote(settings.database_dsn)
            or settings.database_migration_mode != "external"
        ):
            raise ValueError(
                "Configure runtime DATABASE_URL and external migration mode"
            )
        if any(c in unquote(parsed.password) for c in "\r\n\x00"):
            raise ValueError("Runtime password cannot contain psql control input")
        role = unquote(parsed.username)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", role) is None:
            raise ValueError("Use an ASCII PostgreSQL runtime role identifier")
        if role in {"semantix", "postgres"} or role.startswith("pg_"):
            raise ValueError("Use a separate restricted PostgreSQL runtime role")
        pg_local = parsed.hostname == "postgres"
        if pg_local and (
            parsed.port not in (None, 5432)
            or parsed.path != "/semantix"
            or parsed.query
        ):
            raise ValueError("Local PostgreSQL requires postgres:5432/semantix")
    redis_local = False
    if settings.cache_backend == "redis":
        if settings.redis_url is None:
            raise ValueError("Configure REDIS_URL")
        parsed = urlsplit(settings.redis_url.get_secret_value())
        if (
            parsed.hostname is None
            or parsed.hostname.endswith(".invalid")
            or "replace-" in unquote(settings.redis_url.get_secret_value())
        ):
            raise ValueError("Replace the Redis URL placeholder")
        redis_local = parsed.hostname == "redis"
        if redis_local and (
            parsed.scheme != "redis"
            or parsed.port not in (None, 6379)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/", "/0")
        ):
            raise ValueError("Local Redis requires redis://redis:6379/0")
    create_default_provider_registry(settings).resolve(
        settings.embedding_provider, settings.generation_provider
    )
    return {"postgres": pg_local, "redis": redis_local}


async def validate_postgres(settings: Settings) -> None:
    """Read existing schemas/checksums with runtime authority; never repair."""
    pool = await asyncpg.create_pool(
        settings.database_dsn,
        min_size=0,
        max_size=1,
        timeout=settings.database_connect_timeout_seconds,
        command_timeout=settings.database_command_timeout_seconds,
    )
    store: PgVectorStore | None = None
    try:
        async with pool.acquire() as connection:
            restricted = await connection.fetchval(
                """
                SELECT NOT (rolsuper OR rolcreatedb OR rolcreaterole
                            OR rolreplication OR rolbypassrls)
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_auth_members WHERE member = r.oid
                  )
                  AND NOT has_database_privilege(current_user, current_database(), 'CREATE')
                  AND NOT EXISTS (SELECT 1 FROM pg_namespace n
                      WHERE n.nspname !~ '^pg_'
                        AND n.nspname <> 'information_schema'
                        AND has_schema_privilege(current_user, n.oid, 'CREATE'))
                FROM pg_roles r WHERE rolname = current_user
                """
            )
            if not restricted:
                raise ValueError("PostgreSQL runtime account has setup authority")
            tables: list[str] = []
            if settings.cache_backend == "pgvector":
                tables.append("semantix.cache_namespace_counters")
            if settings.coordination_backend == "postgres":
                tables.extend(coordination_database.COORDINATION_TABLES)
            if settings.evaluation_dataset_storage == "postgres":
                tables.extend(evaluation_database.EVALUATION_DATASET_TABLES)
            if settings.evaluation_run_history_storage == "postgres":
                tables.extend(evaluation_database.EVALUATION_RUN_HISTORY_TABLES)
            accessible = await connection.fetchval(
                """
                SELECT COALESCE(bool_and(
                    to_regclass(t) IS NOT NULL
                    AND has_table_privilege(current_user, to_regclass(t), 'SELECT')
                    AND has_table_privilege(current_user, to_regclass(t), 'INSERT')
                    AND has_table_privilege(current_user, to_regclass(t), 'UPDATE')
                    AND has_table_privilege(current_user, to_regclass(t), 'DELETE')
                ), false) FROM unnest($1::text[]) AS required(t)
                """,
                tables,
            )
            if not accessible:
                raise ValueError("Existing server feature tables/grants are incomplete")
        if settings.cache_backend == "pgvector":
            metadata = (
                create_default_provider_registry(settings)
                .resolve(settings.embedding_provider, settings.generation_provider)
                .embedding_metadata
            )
            store = PgVectorStore(
                pool=pool,
                embedding_space=EmbeddingSpace(
                    identity=metadata.space, dimensions=metadata.dimensions
                ),
                schema=settings.cache_pgvector_schema,
                table_prefix=settings.cache_pgvector_table_prefix,
                operation_timeout_seconds=settings.database_command_timeout_seconds,
            )
            await store.validate_schema()
    finally:
        # This job owns no active writes; public termination also fences cancellation.
        pool.terminate()
        if store is not None:
            await store.aclose()


async def setup(
    settings: Settings, *, fresh: dict[str, bool], migration_url: str | None = None
) -> None:
    selected = plan(settings)
    if any(fresh.get(name, False) and not selected[name] for name in selected):
        raise ValueError("Fresh setup is restricted to recognized local services")
    if settings.database_required:
        if fresh.get("postgres", False):
            # Operator authority arrives through stdin, never Docker env metadata.
            if migration_url is None:
                raise ValueError(
                    "Fresh PostgreSQL requires separate migration authority"
                )
            operator = urlsplit(migration_url)
            if (
                operator.scheme not in {"postgres", "postgresql"}
                or operator.hostname != "postgres"
                or operator.port != 5432
                or operator.path != "/semantix"
                or operator.query
                or operator.fragment
            ):
                raise ValueError(
                    "Migration authority must target the owned local database"
                )
            os.environ["MIGRATION_DATABASE_URL"] = migration_url
            parsed = urlsplit(settings.database_dsn)
            os.environ["DATABASE_RUNTIME_ROLE"] = unquote(parsed.username or "")
            os.environ["CACHE_BACKEND"] = settings.cache_backend
            try:
                await migrate.run()
            finally:
                os.environ.pop("MIGRATION_DATABASE_URL", None)
                os.environ.pop("DATABASE_RUNTIME_ROLE", None)
        await validate_postgres(settings)
    if settings.cache_backend == "redis":
        if settings.redis_url is None:
            raise ValueError("Configure REDIS_URL")
        if fresh.get("redis", False):
            await initialize_redis(
                settings, initialization_url=settings.redis_url.get_secret_value()
            )
        metadata = (
            create_default_provider_registry(settings)
            .resolve(settings.embedding_provider, settings.generation_provider)
            .embedding_metadata
        )
        store = await RedisStore.connect(
            url=settings.redis_url.get_secret_value(),
            embedding_space=EmbeddingSpace(
                identity=metadata.space, dimensions=metadata.dimensions
            ),
            key_prefix=settings.redis_key_prefix,
            max_size=settings.max_cache_size,
            default_ttl_seconds=settings.cache_ttl_seconds,
            operation_timeout_seconds=settings.redis_operation_timeout_seconds,
            close_timeout_seconds=settings.redis_close_timeout_seconds,
        )
        try:
            await store.validate_schema()
        finally:
            await store.aclose()


async def run() -> None:
    settings = get_settings()
    selected = plan(settings)
    if sys.argv[1:] == ["check"]:
        sys.stdout.write(json.dumps(selected) + "\n")
        return
    if sys.argv[1:] != ["setup"]:
        raise ValueError("Expected check or setup")
    raw: object = json.loads(sys.stdin.read(1024))
    if not isinstance(raw, dict):
        raise TypeError("Invalid fresh-volume receipt")
    values = cast(dict[str, object], raw)
    if set(values) != {"postgres", "redis", "migration_url"} or any(
        type(values[name]) is not bool for name in selected
    ):
        raise ValueError("Invalid fresh-volume receipt")
    migration_url = values["migration_url"]
    if migration_url is not None and not isinstance(migration_url, str):
        raise ValueError("Invalid migration authority")
    fresh = {name: values[name] is True for name in selected}
    if (migration_url is not None) != fresh["postgres"]:
        raise ValueError(
            "Migration authority is only accepted for fresh owned PostgreSQL"
        )
    async with asyncio.timeout(150):
        await setup(settings, fresh=fresh, migration_url=migration_url)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception:  # noqa: BLE001 - CLI boundary must never render private validation/driver inputs
        # CLI trust boundary: driver/validation errors may contain private inputs.
        sys.stderr.write(
            "Development storage check/setup failed. Verify configuration, runtime "
            "credentials and existing schema; use explicit operator recovery for "
            "partial or incompatible storage. No automatic repair was attempted.\n"
        )
        raise SystemExit(1) from None
