from __future__ import annotations

import json
import secrets
import select
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import httpx
import pytest

from app.core.config import Settings

BACKEND_ROOT = Path(__file__).parents[2]
REQUEST_LIMIT = Settings.model_fields["max_request_body_bytes"].default
assert isinstance(REQUEST_LIMIT, int)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return cast(int, listener.getsockname()[1])


def _wait_until_ready(process: subprocess.Popen[str], base_url: str) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"Uvicorn exited before startup with code {process.returncode}")
        try:
            if httpx.get(f"{base_url}/health", timeout=0.5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    pytest.fail("Uvicorn did not become ready")


@pytest.fixture(scope="module")
def real_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path]]:
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    log_path = tmp_path_factory.mktemp("body-limit") / "uvicorn.log"
    with log_path.open("w", encoding="utf-8") as log_stream:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "tests.uvicorn_body_limit_app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=BACKEND_ROOT,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        try:
            _wait_until_ready(process, base_url)
            yield base_url, log_path
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _json_body(size: int, marker: bytes = b"a") -> bytes:
    prefix = b'{"prompt":"'
    suffix = b'"}'
    return prefix + marker * (size - len(prefix) - len(suffix)) + suffix


def _receive_response(connection: socket.socket, output: bytearray) -> None:
    while True:
        try:
            part = connection.recv(65_536)
        except (ConnectionResetError, OSError):
            return
        if not part:
            return
        output.extend(part)


def _raw_post(
    base_url: str,
    body: bytes,
    *,
    chunked: bool,
) -> tuple[int, dict[str, object], int]:
    port = int(base_url.rsplit(":", 1)[1])
    headers = [
        "POST /api/v1/query HTTP/1.1",
        f"Host: 127.0.0.1:{port}",
        "Content-Type: application/json",
        "Connection: close",
        ("Transfer-Encoding: chunked" if chunked else f"Content-Length: {len(body)}"),
        "",
        "",
    ]
    response = bytearray()
    sent = 0
    with socket.create_connection(("127.0.0.1", port), timeout=10) as connection:
        connection.settimeout(10)
        reader = threading.Thread(
            target=_receive_response,
            args=(connection, response),
            daemon=True,
        )
        reader.start()
        connection.sendall("\r\n".join(headers).encode("ascii"))
        if chunked:
            for offset in range(0, len(body), 16_384):
                part = body[offset : offset + 16_384]
                try:
                    connection.sendall(
                        f"{len(part):X}\r\n".encode("ascii") + part + b"\r\n"
                    )
                    sent += len(part)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
                if response or select.select([connection], [], [], 0.005)[0]:
                    break
            if not response:
                try:
                    connection.sendall(b"0\r\n\r\n")
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
        else:
            try:
                connection.sendall(body)
                sent = len(body)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
        reader.join(timeout=10)
    head, separator, payload = bytes(response).partition(b"\r\n\r\n")
    assert separator
    status = int(head.split(b"\r\n", 1)[0].split()[1])
    return status, json.loads(payload), sent


def _runtime_counts(base_url: str) -> tuple[int, int]:
    response = httpx.get(f"{base_url}/api/v1/metrics", timeout=5)
    assert response.status_code == 200
    payload = response.json()
    return cast(int, payload["provider_calls"]), cast(int, payload["request_count"])


def test_real_uvicorn_preserves_request_size_contract(
    real_server: tuple[str, Path],
) -> None:
    base_url, log_path = real_server
    overflow_marker = f"overflow-{secrets.token_hex(16)}"
    oversized_cases = [
        (_json_body(REQUEST_LIMIT + 1), False),
        (_json_body(REQUEST_LIMIT + 1, b"b"), True),
        (_json_body(3 * 1024 * 1024, b"c"), True),
        (("{" + overflow_marker).encode() + b"x" * REQUEST_LIMIT, True),
    ]
    for body, chunked in oversized_cases:
        status, payload, _ = _raw_post(base_url, body, chunked=chunked)
        assert status == 413
        assert payload == {
            "error": "request_too_large",
            "detail": f"Request body exceeds the {REQUEST_LIMIT}-byte limit.",
        }
    assert _runtime_counts(base_url) == (0, 0)

    exact_status, exact_payload, _ = _raw_post(
        base_url,
        _json_body(REQUEST_LIMIT),
        chunked=True,
    )
    assert exact_status == 422
    assert exact_payload["error"] == "validation_error"

    invalid_status, invalid_payload, _ = _raw_post(
        base_url,
        b'{"prompt":',
        chunked=True,
    )
    assert invalid_status == 422
    assert invalid_payload["error"] == "validation_error"

    normal_status, normal_payload, _ = _raw_post(
        base_url,
        b'{"prompt":"chunked-normal","private":true}',
        chunked=True,
    )
    assert normal_status == 200
    assert normal_payload["provider_called"] is True
    assert httpx.get(f"{base_url}/health", timeout=5).status_code == 200

    output = log_path.read_text(encoding="utf-8")
    assert overflow_marker not in output
