"""Compatibility entry point for the shared database migration command."""

import asyncio

from app.infrastructure.migrate import MigrationSettings, run

__all__ = ["MigrationSettings", "run"]


if __name__ == "__main__":
    asyncio.run(run())
