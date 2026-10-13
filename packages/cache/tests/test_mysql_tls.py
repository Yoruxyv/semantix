"""Public verified TLS, authentication, default-loop and owner-thread evidence."""

import asyncio
import inspect
import socket
import ssl
import sys
import threading
import traceback
from typing import Any
from uuid import uuid4

import pymysql
import pytest

from examples.store_conformance import SPACE
from examples.store_conformance.cases import entry
from semantix_cache import CacheStoreError
from semantix_cache.stores.mysql import MySQLStore

from .mysql_helpers import new_database, options, settings

pytestmark = pytest.mark.mysql


@pytest.mark.parametrize(
    "case", ["wrong_name", "untrusted", "expired", "no_tls", "wrong_password"]
)
async def test_verified_tls_and_authentication_fail_closed(
    case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = settings()
    name = await new_database()
    config = options(name) | {"embedding_space": SPACE, "default_ttl_seconds": None}
    await MySQLStore.initialize_schema(**config)
    if case == "wrong_name":
        config["tls_hostname"] = "wrong.invalid"
    elif case == "untrusted":
        config["ca_file"] = fixture["untrusted_ca_file"]
    elif case in {"expired", "no_tls"}:
        config["port"] = fixture[case + "_port"]
    else:
        config["password"] = str(uuid4()) + "-invalid-password-marker"
    codes: list[int] = []
    certificate_codes: list[int] = []
    original = pymysql.Connection.connect

    def connect(connection: Any, sock: socket.socket | None = None) -> None:
        try:
            original(connection, sock=sock)
        except Exception as error:
            if isinstance(error, pymysql.Error):
                codes.append(error.args[0])
            current: BaseException | None = error
            while current is not None:
                if isinstance(current, ssl.SSLCertVerificationError):
                    certificate_codes.append(current.verify_code)
                current = current.__context__
            raise

    monkeypatch.setattr(pymysql.Connection, "connect", connect)
    before = {
        thread.ident
        for thread in threading.enumerate()
        if thread.name.startswith("semantix-mysql")
    }
    with pytest.raises(CacheStoreError) as caught:
        await MySQLStore.connect(**config)
    if case in {"wrong_name", "untrusted", "expired"}:
        assert certificate_codes, "Failure must come from real certificate verification"
        assert (
            certificate_codes[0]
            in {"wrong_name": {62}, "untrusted": {19, 20, 21}, "expired": {10}}[case]
        )
    else:
        assert codes == [{"no_tls": 2026, "wrong_password": 1045}[case]]
    error = caught.value
    assert error.__cause__ is None
    assert error.__context__ is None
    exposed = str(error.args) + repr(error) + "".join(traceback.format_exception(error))
    for private in (
        fixture["password"],
        "private-invalid-password-marker",
        str(fixture["ca_file"]),
        "wrong.invalid",
    ):
        assert private not in exposed
    assert {
        thread.ident
        for thread in threading.enumerate()
        if thread.name.startswith("semantix-mysql")
    } == before


async def test_public_socket_signature_default_loop_and_owner_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert "sock" in inspect.signature(pymysql.Connection.connect).parameters
    loop = asyncio.get_running_loop()
    assert type(loop).__name__ == (
        "ProactorEventLoop" if sys.platform == "win32" else "_UnixSelectorEventLoop"
    )
    threads = []
    original_connect, original_cursor, original_close = (
        pymysql.Connection.connect,
        pymysql.Connection.cursor,
        pymysql.Connection.close,
    )

    def connect(connection: Any, sock: socket.socket | None = None) -> None:
        threads.append(threading.get_ident())
        assert sock is not None
        assert sock.family == socket.AF_INET
        original_connect(connection, sock=sock)

    def cursor(connection: Any, *args: Any, **kwargs: Any) -> Any:
        threads.append(threading.get_ident())
        return original_cursor(connection, *args, **kwargs)

    def close(connection: Any) -> None:
        threads.append(threading.get_ident())
        original_close(connection)

    name = await new_database()
    config = options(name) | {"embedding_space": SPACE, "default_ttl_seconds": None}
    await MySQLStore.initialize_schema(**config)
    with monkeypatch.context() as patch:
        patch.setattr(pymysql.Connection, "connect", connect)
        patch.setattr(pymysql.Connection, "cursor", cursor)
        patch.setattr(pymysql.Connection, "close", close)
        async with await MySQLStore.connect(**config) as store:
            await store.put(entry("owner"))
            assert await store.find_nearest((1, 0), namespace="default")
            owner = store._worker.thread
    assert owner is not None
    assert not owner.is_alive()
    assert set(threads) == {owner.ident}
    assert owner.ident != threading.get_ident()
