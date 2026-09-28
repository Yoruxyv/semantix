"""Exercise the production Nginx config against disposable reset-capable peers."""

import argparse
import re
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
PYTHON_IMAGE = "python:3.14-slim@sha256:83ff1d245a3d57d04152252d3ef9cb361494d0b3395abd65a5ebe91c401c8e83"
NGINX_IMAGE = "nginxinc/nginx-unprivileged:1.31.3-alpine@sha256:f972e5322b9797dc2a6b830030094426437b1ae7032e4644496395336ac6fdac"
SERVER = """import socket
import struct
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = sys.argv[1].encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        self.close_connection = True

    def log_message(self, *_args):
        pass

ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
"""


def run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"{' '.join(args[:3])}: {result.stderr[-1000:]}")
    return result.stdout.strip()


def fetch(port: int, path: str, *, reset: bool = False) -> tuple[int, str]:
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        data=b"reset" if reset else None,
        method="POST" if reset else "GET",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, response.read().decode()
    except HTTPError as error:
        return error.code, error.read().decode()


def wait_for(port: int, expected: set[str]) -> None:
    for _ in range(30):
        try:
            observed = {fetch(port, "/health")[1] for _ in range(12)}
            if observed == expected:
                return
        except (OSError, URLError):
            pass
        time.sleep(1)
    raise AssertionError(f"Gateway never routed to {expected}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-amplification", action="store_true")
    args = parser.parse_args()
    suffix = uuid4().hex[:8]
    network = f"semantix-gateway-reset-{suffix}"
    gateway = f"{network}-gateway"
    peers = {name: f"{network}-{name}" for name in ("backend-a", "backend-b")}

    with tempfile.TemporaryDirectory(prefix="gateway-reset-") as temporary:
        server = Path(temporary) / "server.py"
        server.write_text(SERVER, encoding="utf-8")
        run("docker", "network", "create", network)

        def start_peer(name: str) -> None:
            run(
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                peers[name],
                "--network",
                network,
                "--network-alias",
                name,
                "-v",
                f"{server}:/server.py:ro",
                PYTHON_IMAGE,
                "python",
                "/server.py",
                name,
            )

        try:
            for name in peers:
                start_peer(name)
            run(
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                gateway,
                "--network",
                network,
                "-p",
                "127.0.0.1::8080",
                "-v",
                f"{ROOT / 'frontend' / 'nginx.conf'}:/etc/nginx/conf.d/default.conf:ro",
                "-v",
                f"{ROOT / 'frontend' / 'upstream.prod.conf'}:/etc/nginx/semantix-upstream.conf:ro",
                "-v",
                f"{ROOT / 'frontend' / 'host-proxy.disabled.conf'}:/etc/nginx/host-proxy.conf:ro",
                NGINX_IMAGE,
            )
            port = int(run("docker", "port", gateway, "8080/tcp").rsplit(":", 1)[1])
            wait_for(port, set(peers))
            resets = [fetch(port, "/api/reset", reset=True)[0] for _ in peers]
            assert resets == [502, 502], resets
            selected = re.findall(
                r"status=502 upstream=([0-9.]+):8000", run("docker", "logs", gateway)
            )
            assert len(set(selected[-2:])) == 2, selected
            assert all(
                run("docker", "inspect", "--format", "{{.State.Running}}", peer)
                == "true"
                for peer in peers.values()
            )
            after_reset = fetch(port, "/health")[0]
            assert after_reset == (502 if args.expect_amplification else 200), (
                after_reset
            )
            print(
                f"controlled resets={resets} gateway_health={after_reset}", flush=True
            )

            time.sleep(6)
            run("docker", "stop", peers["backend-a"])
            wait_for(port, {"backend-b"})
            start_peer("backend-a")
            wait_for(port, set(peers))
            print(
                f"gateway reset smoke: resets={resets} after_reset={after_reset} "
                "failover=backend-b recovery=both"
            )
        finally:
            for container in (gateway, *peers.values()):
                subprocess.run(
                    ["docker", "stop", container], capture_output=True, check=False
                )
            run("docker", "network", "rm", network)


if __name__ == "__main__":
    main()
