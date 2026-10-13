"""Public socket/file ownership independent of PyMySQL's close implementation."""

from __future__ import annotations

import socket
import ssl
import threading
from typing import Any, Self, cast

from typing_extensions import override


class Resources:
    def __init__(self) -> None:
        self.owner = threading.get_ident()
        self.files: list[tuple[str, Any]] = []
        self.sockets: list[tuple[str, socket.socket]] = []
        self.uncertain: set[str] = set()
        resources = self

        class Raw(socket.socket):
            @override
            def makefile(self, *args: Any, **kwargs: Any) -> Any:
                if resources.files:
                    raise RuntimeError("Unexpected MySQL handshake buffer")
                result = cast(Any, super().makefile(*args, **kwargs))
                resources.files.append(("handshake-file", result))
                return result

        class TLS(ssl.SSLSocket):
            def __new__(cls, *args: Any, **kwargs: Any) -> Self:
                result = super().__new__(cls, *args, **kwargs)
                # Capture ownership before TLS initialization can fail.
                resources.sockets.append(("tls-socket", result))
                return result

            @override
            def makefile(self, *args: Any, **kwargs: Any) -> Any:
                if len(resources.files) != 1:
                    raise RuntimeError("Unexpected MySQL TLS buffer")
                result = cast(Any, super().makefile(*args, **kwargs))
                resources.files.append(("tls-file", result))
                return result

        self.raw = Raw(socket.AF_INET, socket.SOCK_STREAM)
        self.sockets.append(("raw-socket", self.raw))
        self.tls_type = TLS
        self.remaining: tuple[str, ...] = ("raw-socket",)
        self.handles_closed = False

    def context(self, ca_file: str) -> ssl.SSLContext:
        context = ssl.create_default_context(cafile=ca_file)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        context.sslsocket_class = self.tls_type
        return context

    def retire(self, duplicate: socket.socket | None) -> bool:
        if threading.get_ident() != self.owner:
            raise RuntimeError("MySQL resources belong to their owner thread")
        failed = False
        items = [(name, item, True) for name, item in self.files]
        items.extend((name, item, False) for name, item in self.sockets)
        if duplicate is not None:
            items.append(("duplicate", duplicate, False))
        remaining: list[str] = []
        for name, item, is_file in items:
            closed = item.closed if is_file else item.fileno() == -1
            if not closed:
                try:
                    item.close()
                except Exception:  # noqa: BLE001 -- never stop disposing other owned resources
                    failed = True
                    if item.closed if is_file else item.fileno() == -1:
                        # A failed kernel close may invalidate its handle: never reuse the integer.
                        self.uncertain.add(name)
            if not (item.closed if is_file else item.fileno() == -1):
                remaining.append(name)
        self.handles_closed = not remaining
        self.remaining = tuple(
            remaining + ["unconfirmed-" + name for name in sorted(self.uncertain)]
        )
        return failed or bool(self.remaining)
