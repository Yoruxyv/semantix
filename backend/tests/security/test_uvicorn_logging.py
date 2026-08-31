import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_until_ready(process: subprocess.Popen[str], base_url: str) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail("Uvicorn exited before the regression app became ready")
        try:
            if httpx.get(f"{base_url}/health", timeout=0.5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    pytest.fail("Timed out waiting for the Uvicorn regression app")


def _json_records(output: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


@pytest.mark.parametrize("startup", ["import-string", "app-object"])
def test_registered_secrets_are_redacted_from_real_uvicorn_output(
    startup: str,
    tmp_path: Path,
) -> None:
    custom_secret = f"DOGFOOD_SECRET_{secrets.token_hex(16)}"
    builtin_secret = f"DOGFOOD_SECRET_{secrets.token_hex(16)}"
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONUNBUFFERED": "1",
            "SEMANTIX_TEST_CUSTOM_SECRET": custom_secret,
            "SEMANTIX_TEST_BUILTIN_SECRET": builtin_secret,
            "SEMANTIX_TEST_PORT": str(port),
        }
    )
    if startup == "import-string":
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.uvicorn_secret_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
    else:
        command = [
            sys.executable,
            "-c",
            (
                "import os, uvicorn; "
                "from tests.uvicorn_secret_app import app; "
                "uvicorn.run(app, host='127.0.0.1', "
                "port=int(os.environ['SEMANTIX_TEST_PORT']))"
            ),
        ]

    log_path = tmp_path / "uvicorn.log"
    log_stream = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=Path(__file__).parents[2],
        env=environment,
        stdout=log_stream,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    response: httpx.Response | None = None
    health: httpx.Response | None = None
    try:
        _wait_until_ready(process, base_url)
        response = httpx.post(
            f"{base_url}/api/v1/query",
            json={"prompt": "trigger controlled provider failure"},
            timeout=15,
        )
        health = httpx.get(f"{base_url}/health", timeout=5)
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log_stream.close()
    output = log_path.read_text(encoding="utf-8")

    assert response is not None
    assert response.status_code == 500
    assert response.json() == {"error": "internal_error", "detail": None}
    assert health is not None
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    if custom_secret in output or builtin_secret in output:
        pytest.fail("A configured secret appeared in captured Uvicorn output")

    records = _json_records(output)
    application_errors = [
        record
        for record in records
        if record.get("logger") == "app.core.exceptions"
        and str(record.get("message", "")).startswith("Unhandled error")
    ]
    uvicorn_errors = [
        record
        for record in records
        if record.get("logger") == "uvicorn.error"
        and str(record.get("message", "")).startswith("Exception in ASGI application")
    ]
    access_records = [
        record for record in records if record.get("logger") == "uvicorn.access"
    ]
    if (
        len(application_errors) != 1
        or json.dumps(application_errors[0]).count("[REDACTED]") < 2
    ):
        pytest.fail("The application exception was not logged once with redaction")
    if (
        len(uvicorn_errors) != 1
        or json.dumps(uvicorn_errors[0]).count("[REDACTED]") < 2
    ):
        pytest.fail("The Uvicorn ASGI exception was not logged once with redaction")
    if not access_records:
        pytest.fail("The real-server regression did not capture Uvicorn access logs")
