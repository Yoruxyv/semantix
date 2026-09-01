import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from app.core.logging import configure_logging

_PROVIDER_RESPONSE_MARKER = "SYNTHETIC_PROVIDER_RESPONSE_MARKER"


class _ProviderServer(ThreadingHTTPServer):
    daemon_threads = True


class _ProviderHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(content_length))
        prompt = str(payload.get("prompt", ""))

        if prompt.startswith("transport-failure"):
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        if prompt.startswith("timeout-failure"):
            time.sleep(0.4)
            return
        if prompt.startswith("deadline-failure"):
            self._send_slow_response()
            return
        if prompt.startswith("client-error"):
            self._send_response(400, b"")
            return
        if prompt.startswith("server-error"):
            self._send_response(503, b"")
            return
        self._send_response(
            200,
            b'{"response":"SYNTHETIC_PROVIDER_RESPONSE_MARKER"}',
        )

    def _send_response(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _send_slow_response(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for value in b'{"response":"too late"}':
                time.sleep(0.04)
                self.wfile.write(b"1\r\n" + bytes((value,)) + b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


@pytest.fixture
def provider_endpoint() -> Iterator[tuple[str, str, str, str]]:
    server = _ProviderServer(("127.0.0.1", 0), _ProviderHandler)
    token = secrets.token_hex(12)
    path_marker = f"private-provider-path-{token}"
    query_marker = f"private-query-{token}"
    prompt_marker = f"private-prompt-{token}"
    endpoint = (
        f"http://127.0.0.1:{server.server_port}/{path_marker}/v1%2Fgenerate"
        f"?tenant={query_marker}&encoded={token}%2Fsecret%20space"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield endpoint, path_marker, query_marker, prompt_marker
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def restore_logging_state() -> Iterator[None]:
    loggers = [
        logging.getLogger(),
        logging.getLogger("httpx"),
        logging.getLogger("httpcore"),
    ]
    states = [
        (logger.level, logger.propagate, list(logger.handlers)) for logger in loggers
    ]
    try:
        yield
    finally:
        for logger, (level, propagate, handlers) in zip(loggers, states, strict=True):
            logger.setLevel(level)
            logger.propagate = propagate
            logger.handlers[:] = handlers


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


def test_dependency_request_info_is_suppressed_without_hiding_application_info(
    capsys: pytest.CaptureFixture[str],
    restore_logging_state: None,
) -> None:
    logging.getLogger("httpcore").setLevel(logging.NOTSET)
    configure_logging("INFO", ())
    configure_logging("INFO", ())

    logging.getLogger("app.test").info("APPLICATION_INFO_MARKER")
    logging.getLogger("httpx").info("PRIVATE_PROVIDER_URL_MARKER")
    logging.getLogger("httpx").warning("DEPENDENCY_WARNING_MARKER")

    output = capsys.readouterr().err
    assert output.count("APPLICATION_INFO_MARKER") == 1
    assert output.count("DEPENDENCY_WARNING_MARKER") == 1
    assert "PRIVATE_PROVIDER_URL_MARKER" not in output
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.NOTSET


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


@pytest.mark.parametrize("startup", ["import-string", "app-object"])
def test_provider_urls_are_suppressed_from_complete_real_uvicorn_output(
    startup: str,
    provider_endpoint: tuple[str, str, str, str],
    tmp_path: Path,
) -> None:
    endpoint, path_marker, query_marker, prompt_marker = provider_endpoint
    custom_secret = f"PROVIDER_SECRET_{secrets.token_hex(16)}"
    builtin_secret = f"SETTINGS_SECRET_{secrets.token_hex(16)}"
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONUNBUFFERED": "1",
            "SEMANTIX_TEST_PROVIDER_URL": endpoint,
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
            "tests.uvicorn_provider_url_app:app",
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
                "from tests.uvicorn_provider_url_app import app; "
                "uvicorn.run(app, host='127.0.0.1', "
                "port=int(os.environ['SEMANTIX_TEST_PORT']))"
            ),
        ]

    log_path = tmp_path / "uvicorn-provider-url.log"
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
    responses: dict[str, httpx.Response] = {}
    health: httpx.Response | None = None
    expected_statuses = {
        f"success-{prompt_marker}": 200,
        f"client-error-{prompt_marker}": 502,
        f"server-error-{prompt_marker}": 503,
        f"timeout-failure-{prompt_marker}": 503,
        f"deadline-failure-{prompt_marker}": 503,
        f"transport-failure-{prompt_marker}": 503,
    }
    try:
        _wait_until_ready(process, base_url)
        for prompt in expected_statuses:
            responses[prompt] = httpx.post(
                f"{base_url}/api/v1/query",
                json={"prompt": prompt, "private": True},
                timeout=5,
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

    assert {
        prompt: response.status_code for prompt, response in responses.items()
    } == expected_statuses
    assert health is not None
    assert health.status_code == 200
    assert output.count(endpoint) == 0
    assert output.count(path_marker) == 0
    assert output.count(query_marker) == 0
    assert output.count(prompt_marker) == 0
    assert output.count(_PROVIDER_RESPONSE_MARKER) == 0
    if custom_secret in output or builtin_secret in output:
        pytest.fail("A configured secret appeared in captured Uvicorn output")

    records = _json_records(output)
    assert not [
        record
        for record in records
        if record.get("logger") == "httpx" and record.get("level") == "INFO"
    ]
    assert not [
        record
        for record in records
        if str(record.get("logger", "")).startswith("httpcore")
    ]
    assert any(record.get("logger") == "uvicorn.access" for record in records)
    assert any(
        record.get("logger") == "app.core.exceptions"
        and record.get("level") == "WARNING"
        for record in records
    )
