"""Terminal physical-close policy and compatible startup error visibility."""

import asyncio
import json
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "before_transient",
        "before_persistent",
        "after",
        "startup_before_transient",
        "startup_before_persistent",
        "startup_after",
        "cancel_success",
        "cancel_before_transient",
        "startup_cancel_before",
    ],
)
async def test_terminal_cleanup_and_startup_cause(tmp_path: Path, mode: str) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-B",
        "-m",
        "tests.sqlite_cleanup_smoke",
        str(tmp_path / "physical"),
        mode,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        output, errors = await asyncio.wait_for(process.communicate(), 20)
        assert process.returncode == 0, errors.decode()
        result = json.loads(output)
        assert result["assertions"] == "PASS"
        assert result["native_close_calls"] == 1
        assert result["executor_threads_alive"] == 0
        assert result["physical_state_at_close_boundary"] == (
            "OPEN" if "before" in mode else "CLOSED"
        )
        if mode.startswith("startup_"):
            failure = result["public_failures"][0]
            assert failure["cause"] == "SQLite owned connection cleanup failed"
            assert "controlled close failure" not in json.dumps(failure)
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()
