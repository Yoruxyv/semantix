"""Operation admission is synchronous so close cannot race an admitted operation."""

from collections.abc import Generator
from contextlib import contextmanager

from .errors import CacheBusyError, CacheClosedError


class Lifecycle:
    def __init__(self) -> None:
        self.closed = False
        self.active = 0

    def check_open(self) -> None:
        if self.closed:
            raise CacheClosedError("Resource is closed")

    @contextmanager
    def operation(self) -> Generator[None, None, None]:
        self.check_open()
        self.active += 1
        try:
            yield
        finally:
            self.active -= 1

    def close(self, *, workers: bool = False) -> None:
        if self.active or workers:
            raise CacheBusyError("Resource has active operations")
        self.closed = True
