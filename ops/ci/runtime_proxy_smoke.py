"""Probe the disposable hardened gateway's HTTP and trusted-client boundary."""

import json
import os
import socket
import urllib.error
import urllib.request

HOST = "127.0.0.1"
PORT = int(os.environ.get("SEMANTIX_PORT", "18080"))
BASE = f"http://{HOST}:{PORT}"


def get(path: str, *, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(BASE + path, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers)


def raw(payload: bytes) -> int:
    with socket.create_connection((HOST, PORT), timeout=10) as connection:
        connection.settimeout(10)
        connection.sendall(payload)
        status_line = bytearray()
        while not status_line.endswith(b"\r\n"):
            chunk = connection.recv(1)
            if not chunk:
                raise AssertionError("Gateway closed before an HTTP status line")
            status_line.extend(chunk)
    return int(status_line.split(b" ", 2)[1])


def main() -> None:
    health, headers = get("/health")
    ready, _ = get("/ready")
    assert health == ready == 200, (health, ready)
    for name in (
        "Content-Security-Policy",
        "Referrer-Policy",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Permissions-Policy",
    ):
        assert name in headers, name

    unauthenticated, _ = get("/api/v1/cache/entries?namespace=alpha")
    assert unauthenticated == 401, unauthenticated

    token = os.environ["SEMANTIX_E2E_TOKEN"]
    body = json.dumps({"prompt": "x" * 70000}).encode()
    common = (
        b"POST /api/v1/query HTTP/1.1\r\n"
        b"Host: localhost\r\n"
        + f"Authorization: Bearer {token}\r\n".encode()
        + b"Content-Type: application/json\r\nConnection: close\r\n"
    )
    oversized = raw(common + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    chunked = raw(
        common
        + b"Transfer-Encoding: chunked\r\n\r\n"
        + f"{len(body):x}\r\n".encode()
        + body
        + b"\r\n0\r\n\r\n"
    )
    large_header = raw(
        b"GET /health HTTP/1.1\r\nHost: localhost\r\nX-Padding: "
        + b"x" * 17000
        + b"\r\nConnection: close\r\n\r\n"
    )
    conflicting_framing = raw(
        common + b"Content-Length: 4\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n"
    )
    assert oversized == chunked == 413, (oversized, chunked)
    assert large_header in (400, 431), large_header
    assert conflicting_framing == 400, conflicting_framing

    spoofed = [
        get(
            "/api/v1/auth/session",
            headers={
                "Authorization": "Bearer invalid-token",
                "X-Forwarded-For": f"198.51.100.{index}",
            },
        )[0]
        for index in (1, 2, 3)
    ]
    assert spoofed == [401, 401, 429], spoofed
    print(
        "gateway verification: health=200 ready=200 security_headers=5 "
        f"unauthenticated={unauthenticated} oversized={oversized} "
        f"chunked={chunked} large_header={large_header} "
        f"conflicting_framing={conflicting_framing} "
        f"spoofed_forwarding={spoofed}"
    )


if __name__ == "__main__":
    main()
