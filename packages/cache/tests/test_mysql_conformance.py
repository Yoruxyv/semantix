"""Unmodified shared public contract, including real metadata/lifecycle probes."""

import pytest

from examples.store_conformance import StoreConformance

from .mysql_helpers import store_factory

__all__ = ["store_factory"]
pytestmark = pytest.mark.mysql


class TestMySQLStore(StoreConformance):
    pass
