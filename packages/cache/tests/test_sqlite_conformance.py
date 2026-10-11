"""Unmodified public contract consumed by real file-backed SQLite."""

from examples.store_conformance import StoreConformance

from .sqlite_helpers import store_factory  # noqa: F401 -- pytest fixture


class TestSQLiteStore(StoreConformance):
    """Metadata and blocked numerical worker probes are both enabled."""
