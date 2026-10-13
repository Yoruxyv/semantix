"""Disposable independent-process client; JSON IPC carries no connection secrets."""

import asyncio
import json
import sys
import threading
from datetime import UTC, datetime
from typing import Any

import pymysql
import pytest

from examples.store_conformance import SPACE
from examples.store_conformance.cases import entry
from semantix_cache.stores.mysql import MySQLStore

from .mysql_helpers import options


def send(value: object) -> None:
    sys.stdout.write(json.dumps(value) + "\n")
    sys.stdout.flush()


async def main() -> None:
    name, capacity = sys.argv[1], int(sys.argv[2])
    async with await MySQLStore.connect(
        **options(name),
        embedding_space=SPACE,
        max_size=capacity,
        default_ttl_seconds=None,
    ) as store:
        send("ready")
        for line in sys.stdin:
            command: dict[str, Any] = json.loads(line)
            action = command["action"]
            if action == "stop":
                break
            if action == "crash":
                original = pymysql.Connection.commit

                def commit(
                    connection: Any, side: str = command["side"], saved: Any = original
                ) -> None:
                    if side == "after":
                        saved(connection)
                    send("commit boundary")
                    assert threading.Event().wait(30), (
                        "Parent must terminate this owned process"
                    )

                pytest.MonkeyPatch().setattr(pymysql.Connection, "commit", commit)
                await store.put(
                    entry("crash", created_at=datetime(2020, 1, 1, tzinfo=UTC))
                )
            elif action == "put":
                for _ in range(command["count"]):
                    await store.put(
                        entry(
                            command["prompt"],
                            namespace=command.get("namespace", "default"),
                            created_at=datetime(2020, 1, 1, tzinfo=UTC),
                        )
                    )
                send(True)
            elif action == "hit":
                expected = datetime.fromisoformat(command["revision"])
                hits = [
                    await store.record_hit(
                        command["key"],
                        namespace="default",
                        expected_created_at=expected,
                    )
                    for _ in range(command["count"])
                ]
                send(hits)
            else:
                raise AssertionError("Unknown test command")


if __name__ == "__main__":
    asyncio.run(main())
