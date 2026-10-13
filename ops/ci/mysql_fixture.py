"""Run one command against private, pinned disposable MySQL/TLS fixtures.

This is test infrastructure, not an application launcher. Docker resources carry
an unpredictable ownership label. Private credentials, keys, logs and data remain outside the repository.
"""

# ruff: noqa: T201
# This disposable fixture CLI reports its lifecycle and child results to stdout.

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pymysql

IMAGE = "container-registry.oracle.com/mysql/community-server@sha256:7dcc4add9183664de3a214daf85a50c3ba6cccfd7534f700b6561bf5b41885be"
OWNER = "semantix-mysql-phase5"


def command(args: list[str], *, cwd: Path) -> str:
    result = subprocess.run(  # noqa: S603 -- fixed tool argv and owned paths, no shell
        args, cwd=cwd, capture_output=True, text=True, timeout=90, check=False
    )
    if result.returncode:
        with (cwd / "command-failures.jsonl").open("a", encoding="utf8") as stream:
            stream.write(
                json.dumps(
                    {
                        "args": args,
                        "code": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
                + "\n"
            )
        raise RuntimeError(
            "Disposable fixture command failed; private output retained outside the repository"
        )
    return result.stdout.strip()


def openssl_path() -> str:
    program = shutil.which("openssl")
    if program is not None:
        return program
    git = shutil.which("git")
    if git is not None:
        bundled = Path(git).resolve().parent.parent / "usr" / "bin" / "openssl.exe"
        if bundled.is_file():
            return str(bundled)
    raise RuntimeError(
        "Fixture certificate generation requires an installed OpenSSL CLI"
    )


def certificates(root: Path) -> Path:
    tls = root / "tls"
    tls.mkdir(mode=0o700)
    tool = openssl_path()
    for prefix in ("ca", "untrusted-ca"):
        command(
            [
                tool,
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-sha256",
                "-days",
                "7",
                "-subj",
                "/CN=Semantix disposable " + prefix,
                "-keyout",
                prefix + "-key.pem",
                "-out",
                prefix + ".pem",
                "-addext",
                "basicConstraints=critical,CA:TRUE",
                "-addext",
                "keyUsage=critical,keyCertSign,cRLSign",
            ],
            cwd=tls,
        )
    command(
        [
            tool,
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=localhost",
            "-keyout",
            "server-key.pem",
            "-out",
            "server.csr",
        ],
        cwd=tls,
    )
    extensions = "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost,IP:127.0.0.1\n"
    (tls / "server.ext").write_text(extensions, encoding="ascii")
    command(
        [
            tool,
            "x509",
            "-req",
            "-in",
            "server.csr",
            "-CA",
            "ca.pem",
            "-CAkey",
            "ca-key.pem",
            "-CAcreateserial",
            "-days",
            "7",
            "-sha256",
            "-extfile",
            "server.ext",
            "-out",
            "server.pem",
        ],
        cwd=tls,
    )
    command(
        [
            tool,
            "verify",
            "-x509_strict",
            "-verify_hostname",
            "localhost",
            "-CAfile",
            "ca.pem",
            "server.pem",
        ],
        cwd=tls,
    )
    (tls / "index.txt").touch()
    (tls / "serial").write_text("1000\n", encoding="ascii")
    (tls / "issued").mkdir()
    (tls / "ca.cnf").write_text(
        "[ca]\ndefault_ca=local\n[local]\ndatabase=index.txt\nnew_certs_dir=issued\ncertificate=ca.pem\nprivate_key=ca-key.pem\nserial=serial\ndefault_md=sha256\npolicy=policy\nx509_extensions=server\n[policy]\ncommonName=supplied\n[server]\n"
        + extensions,
        encoding="ascii",
    )
    command(
        [
            tool,
            "ca",
            "-batch",
            "-notext",
            "-config",
            "ca.cnf",
            "-startdate",
            "20200101000000Z",
            "-enddate",
            "20200102000000Z",
            "-in",
            "server.csr",
            "-out",
            "expired.pem",
        ],
        cwd=tls,
    )
    return tls


def connection(config: dict[str, Any]) -> Any:
    context = ssl.create_default_context(cafile=config["ca_file"])
    result = pymysql.Connection(
        host="localhost",
        port=config["port"],
        user="root",
        password=config["password"].encode("utf8"),
        ssl=context,
        autocommit=True,
        connect_timeout=2,
        read_timeout=0.5,
        write_timeout=0.5,
        defer_connect=True,
    )
    raw = socket.create_connection(("127.0.0.1", config["port"]), timeout=2)
    try:
        result.connect(sock=raw)
        return result
    except BaseException:
        raw.close()
        if result.open:
            result.close()
        raise


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.identifier = secrets.token_hex(8)
        self.password = secrets.token_hex(32)
        self.containers: list[str] = []
        self.volumes: list[str] = []
        self.tls = certificates(root)
        if os.name != "nt":
            # Only this freshly created TLS directory is changed, never developer data.
            command(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    f"semantix-mysql-p5-{self.identifier}-permissions",
                    "--label",
                    f"semantix.fixture={self.identifier}",
                    "--label",
                    f"semantix.owner={OWNER}",
                    "--user",
                    "0",
                    "--mount",
                    f"type=bind,source={self.tls},target=/tls",
                    "--entrypoint",
                    "/bin/sh",
                    IMAGE,
                    "-c",
                    "chown -R 27:27 /tls && chmod 755 /tls && chmod 600 /tls/server-key.pem && chmod 644 /tls/ca.pem /tls/server.pem /tls/expired.pem",
                ],
                cwd=self.root,
            )

    def start(self, kind: str) -> dict[str, Any]:
        config: dict[str, Any] = {
            "fixture_owner": OWNER,
            "fixture_id": self.identifier,
            "address": "127.0.0.1",
            "tls_hostname": "localhost",
            "ca_file": str(self.tls / "ca.pem"),
            "untrusted_ca_file": str(self.tls / "untrusted-ca.pem"),
            "user": "root",
            "password": self.password,
        }
        common = [
            "--innodb-flush-log-at-trx-commit=1",
            "--skip-log-bin",
            "--innodb-buffer-pool-size=64M",
            "--innodb-redo-log-capacity=64M",
            "--mysqlx=0",
        ]
        name = f"semantix-mysql-p5-{self.identifier}-{kind}"
        volume = name + "-data"
        command(
            [
                "docker",
                "volume",
                "create",
                "--label",
                f"semantix.fixture={self.identifier}",
                "--label",
                f"semantix.owner={OWNER}",
                volume,
            ],
            cwd=self.root,
        )
        self.volumes.append(volume)
        env = self.root / (kind + ".env")
        env.write_text(
            "MYSQL_ROOT_PASSWORD=" + self.password + "\nMYSQL_ROOT_HOST=%\n",
            encoding="ascii",
        )
        env.chmod(0o600)
        tls = (
            ["--tls-version=", "--require-secure-transport=OFF"]
            if kind == "no_tls"
            else [
                "--require-secure-transport=ON",
                "--ssl-ca=/tls/ca.pem",
                "--ssl-cert=/tls/"
                + ("expired.pem" if kind == "expired" else "server.pem"),
                "--ssl-key=/tls/server-key.pem",
            ]
        )
        command(
            [
                "docker",
                "create",
                "--name",
                name,
                "--label",
                f"semantix.fixture={self.identifier}",
                "--label",
                f"semantix.owner={OWNER}",
                "--env-file",
                str(env),
                "--publish",
                "127.0.0.1::3306",
                "--mount",
                f"type=bind,source={self.tls},target=/tls,readonly",
                "--mount",
                f"type=volume,source={volume},target=/var/lib/mysql",
                IMAGE,
                *common,
                *tls,
            ],
            cwd=self.root,
        )
        self.containers.append(name)
        command(["docker", "start", name], cwd=self.root)
        config["port"] = int(
            command(["docker", "port", name, "3306/tcp"], cwd=self.root).rsplit(":", 1)[
                1
            ]
        )
        # Readiness retries only connect/probe; no business transaction is replayed.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if kind != "valid":
                    with socket.create_connection(
                        ("127.0.0.1", config["port"]), timeout=0.5
                    ) as probe:
                        probe.settimeout(0.5)
                        if probe.recv(128):
                            return config
                else:
                    database = connection(config)
                    try:
                        with database.cursor() as cursor:
                            cursor.execute("SELECT @@server_uuid,@@version", ())
                            config["server_uuid"], config["server_version"] = (
                                cursor.fetchone()
                            )
                            return config
                    finally:
                        database.close()
            except (OSError, pymysql.Error):
                time.sleep(0.1)
        raise RuntimeError(
            "Bounded disposable MySQL readiness failed; inspect private fixture logs"
        )

    def close(self) -> None:
        for name in reversed(self.containers):
            inspected = json.loads(command(["docker", "inspect", name], cwd=self.root))[
                0
            ]
            labels = inspected["Config"]["Labels"]
            expected_image = command(
                ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"],
                cwd=self.root,
            )
            if (
                labels.get("semantix.fixture") != self.identifier
                or labels.get("semantix.owner") != OWNER
                or inspected["Image"] != expected_image
                or inspected["Config"]["Image"] != IMAGE
            ):
                raise RuntimeError("Fixture ownership changed; refusing cleanup")
            command(["docker", "stop", "--timeout", "5", name], cwd=self.root)
        for volume in self.volumes:
            inspected = json.loads(
                command(["docker", "volume", "inspect", volume], cwd=self.root)
            )[0]
            if (
                inspected["Labels"].get("semantix.fixture") != self.identifier
                or inspected["Labels"].get("semantix.owner") != OWNER
            ):
                raise RuntimeError("Fixture volume ownership changed; refusing cleanup")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    child = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not child:
        parser.error("A test command is required after --")
    root = Path(tempfile.mkdtemp(prefix="semantix-mysql-p5-"))
    root.chmod(0o700)
    fixture = Fixture(root)
    try:
        valid = fixture.start("valid")
        valid["expired_port"] = fixture.start("expired")["port"]
        valid["no_tls_port"] = fixture.start("no_tls")["port"]
        receipt = root / "connection.json"
        receipt.write_text(json.dumps(valid), encoding="utf8")
        receipt.chmod(0o600)
        env = dict(os.environ, MYSQL_TEST_CONFIG=str(receipt))
        print("Disposable MySQL fixture ready: " + valid["server_version"], flush=True)
        result = subprocess.run(  # noqa: S603 -- explicit operator-supplied test argv, no shell
            child, env=env, capture_output=True, check=False, timeout=1800
        )
        (root / "child.stdout.log").write_bytes(result.stdout)
        (root / "child.stderr.log").write_bytes(result.stderr)
        for output in (result.stdout, result.stderr):
            sys.stdout.write(
                output.decode("utf8", errors="replace").replace(
                    fixture.password, "[redacted fixture credential]"
                )
            )
        print("Fixture child exit: " + str(result.returncode), flush=True)
        return result.returncode
    finally:
        fixture.close()
        print(
            "Owned fixtures stopped; private data retained at " + str(root), flush=True
        )


if __name__ == "__main__":
    raise SystemExit(main())
