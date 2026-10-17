"""Bounded TLS/ALPN checks against an explicitly configured disposable PostgreSQL."""

from __future__ import annotations

import asyncio
import os
import ssl
import traceback
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

import asyncpg

from semantix_cache import (
    CacheConfigurationError,
    CacheTimeoutError,
    EmbeddingSpace,
)
from semantix_cache.stores.pgvector import PgVectorStore


async def main() -> None:
    original = urlsplit(os.environ["PGVECTOR_TEST_DATABASE_URL"])
    ca = Path(os.environ["TLS_CA"])
    bad_ca = Path(os.environ["TLS_BAD_CA"])
    driver = os.environ["EXPECTED_ASYNCPG_DRIVER"]
    assert asyncpg.__version__ == driver
    assert driver in {"0.31.0", "0.32.0"}
    space = EmbeddingSpace(identity="tls-certification", dimensions=2)

    def address(
        *, host: str = "localhost", root: Path = ca, direct: bool = False
    ) -> str:
        return urlunsplit(
            original._replace(
                netloc=original.netloc.replace("127.0.0.1", host),
                query=urlencode(
                    {
                        "sslmode": "verify-full",
                        "sslrootcert": str(root),
                        "sslnegotiation": "direct" if direct else "postgres",
                    }
                ),
            )
        )

    async def connect(
        *,
        direct: bool = False,
        explicit: bool = False,
        root: Path = ca,
        host: str = "localhost",
        expected: tuple[type[Exception], ...] = (),
    ) -> None:
        context = None
        if explicit:
            context = ssl.create_default_context(cafile=str(root))
            context.set_alpn_protocols(["postgresql"])
        try:
            connection = await asyncpg.connect(
                address(direct=direct, root=root, host=host),
                ssl=context,
                timeout=3,
                command_timeout=3,
            )
        except expected as error:
            assert not isinstance(error, TimeoutError), "Rejection must be explicit"
            return
        try:
            assert not expected, "Invalid TLS configuration accepted"
            assert (
                await connection.fetchval(
                    "SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()"
                )
                is True
            )
            assert await connection.fetchval("SELECT 42") == 42
        finally:
            await connection.close(timeout=3)

    async def owned(
        *, direct: bool, reject: bool = False, root: Path = ca, host: str = "localhost"
    ) -> None:
        dsn = address(direct=direct, root=root, host=host)
        try:
            store = await PgVectorStore.connect(
                dsn=dsn,
                embedding_space=space,
                connect_timeout_seconds=3,
                operation_timeout_seconds=3,
                close_timeout_seconds=3,
            )
        except CacheConfigurationError as error:
            assert reject
            assert error.__context__ is None
            for rendered in (
                str(error),
                repr(error),
                "".join(traceback.format_exception(error)),
            ):
                assert dsn not in rendered
                assert original.password and original.password not in rendered
            return
        try:
            assert not reject, "Invalid owned-pool TLS configuration accepted"
            async with store._pool.acquire(timeout=3) as connection:
                assert (
                    await connection.fetchval(
                        "SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()"
                    )
                    is True
                )
        finally:
            await store.aclose()
            assert store._pool.get_size() == 0

    async def borrowed(*, direct: bool) -> None:
        context = ssl.create_default_context(cafile=str(ca))
        context.set_alpn_protocols(["postgresql"])
        pool = await asyncpg.create_pool(
            address(direct=direct),
            ssl=context,
            min_size=1,
            max_size=2,
            timeout=3,
            command_timeout=3,
        )
        try:
            store = PgVectorStore(pool=pool, embedding_space=space)
            async with pool.acquire(timeout=3) as connection:
                pid = connection.get_server_pid()
                assert (
                    await connection.fetchval(
                        "SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()"
                    )
                    is True
                )
                await store.aclose()
                assert not pool.is_closing()
                assert await connection.fetchval("SELECT pg_backend_pid()") == pid
        finally:
            try:
                async with asyncio.timeout(3):
                    await pool.close()
            finally:
                pool.terminate()

    async with asyncio.timeout(60):
        for direct in (False, True):
            await connect(direct=direct, explicit=direct)
            await borrowed(direct=direct)
            await connect(
                direct=direct,
                explicit=direct,
                root=bad_ca,
                expected=(ssl.SSLCertVerificationError,),
            )
            await connect(
                direct=direct,
                explicit=direct,
                host="127.0.0.1",
                expected=(ssl.SSLCertVerificationError,),
            )
            if not direct or driver == "0.32.0":
                await owned(direct=direct)
                await owned(direct=direct, reject=True, root=bad_ca)
                await owned(direct=direct, reject=True, host="127.0.0.1")
        if driver == "0.32.0":
            await connect(direct=True)
        else:
            await connect(direct=True, expected=(OSError, asyncpg.PostgresError))
        for direct in (False, True):
            for cancel in (False, True):
                await stalled_negotiation(space, direct=direct, cancel=cancel)
    print(
        f"Verified asyncpg {driver}: TLS/ALPN, CA/hostname rejection, safe errors and negotiation cleanup"
    )


async def stalled_negotiation(
    space: EmbeddingSpace, *, direct: bool, cancel: bool
) -> None:
    accepted = asyncio.Event()
    disconnected = asyncio.Event()
    handlers: list[asyncio.Task[None]] = []

    async def handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            assert await reader.read(4096)
            accepted.set()
            assert await reader.read() == b""
            disconnected.set()
        finally:
            writer.close()
            await writer.wait_closed()

    def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        handlers.append(asyncio.create_task(handle(reader, writer)))

    server = await asyncio.start_server(accept, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    dsn = f"postgresql://disposable@127.0.0.1:{port}/test?sslmode=require"
    if direct:
        dsn += "&sslnegotiation=direct"
    task = asyncio.create_task(
        PgVectorStore.connect(
            dsn=dsn,
            embedding_space=space,
            connect_timeout_seconds=2 if cancel else 0.2,
        )
    )
    try:
        await asyncio.wait_for(accepted.wait(), timeout=3)
        if cancel:
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, CacheTimeoutError) as error:
            assert isinstance(
                error, asyncio.CancelledError if cancel else CacheTimeoutError
            )
        else:
            raise AssertionError("Stalled negotiation succeeded")
        await asyncio.wait_for(disconnected.wait(), timeout=3)
        await asyncio.wait_for(asyncio.gather(*handlers), timeout=3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server.close()
        await server.wait_closed()
        for handler in handlers:
            if not handler.done():
                handler.cancel()
        await asyncio.gather(*handlers, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
