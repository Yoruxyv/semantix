"""Test-only opaque TCP relay; end-to-end TLS terminates at the real MySQL server."""

from __future__ import annotations

import select
import socket
import threading
from contextlib import suppress


class Relay:
    def __init__(self, target: tuple[str, int]) -> None:
        self.target = target
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.listener.listen(1)
        self.listener.settimeout(0.1)
        self.stop = threading.Event()
        self.block_downstream = threading.Event()
        self.downstream_blocked = threading.Event()
        self.upstream_after_block = threading.Event()
        self.failure: str | None = None
        self.thread = threading.Thread(target=self._run, name="mysql-test-relay")
        self.thread.start()

    def _run(self) -> None:
        client = server = None
        try:
            while not self.stop.is_set():
                try:
                    client, _ = self.listener.accept()
                    break
                except TimeoutError:
                    continue
            if client is None:
                return
            server = socket.create_connection(self.target, timeout=2)
            client.settimeout(0.5)
            server.settimeout(0.5)
            while not self.stop.is_set():
                readers = (
                    [client] if self.block_downstream.is_set() else [client, server]
                )
                readable, _, _ = select.select(readers, [], [], 0.01)
                if self.block_downstream.is_set():
                    self.downstream_blocked.set()
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    destination = server if source is client else client
                    destination.sendall(data)
                    if source is client and self.block_downstream.is_set():
                        self.upstream_after_block.set()
        except OSError:
            if not self.stop.is_set():
                self.failure = "relay transport ended"
        finally:
            for connection in (client, server, self.listener):
                if connection is not None:
                    connection.close()

    def close(self) -> None:
        self.stop.set()
        with suppress(OSError):
            self.listener.shutdown(socket.SHUT_RDWR)
        self.thread.join(timeout=3)
        assert not self.thread.is_alive(), "Owned test relay did not terminate"
