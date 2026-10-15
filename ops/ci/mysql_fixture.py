"""Run one command against private, pinned disposable MySQL/TLS fixtures.

This is test infrastructure, not an application launcher. Docker resources carry
an unpredictable ownership label. Credentials travel through child environments;
only sanitized diagnostics and database volumes are retained.
"""

# ruff: noqa: T201
# This disposable fixture CLI reports its lifecycle and child results to stdout.

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pymysql

IMAGE = "container-registry.oracle.com/mysql/community-server@sha256:7dcc4add9183664de3a214daf85a50c3ba6cccfd7534f700b6561bf5b41885be"
OWNER = "semantix-mysql-phase5"


def windows_acl(path: Path) -> dict[str, Any]:
    program = (
        Path(os.environ["SYSTEMROOT"])
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    script = """$ErrorActionPreference = 'Stop'
$acl = Get-Acl -LiteralPath $env:SEMANTIX_FIXTURE_ACL_PATH
@{owner=$acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value;
  protected=$acl.AreAccessRulesProtected;
  rules=@($acl.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier]) | ForEach-Object {
    @{sid=$_.IdentityReference.Value; type=$_.AccessControlType.ToString()}
  })} | ConvertTo-Json -Depth 4 -Compress
"""
    result = subprocess.run(  # noqa: S603 -- fixed Windows ACL inspection, no secret arguments
        [str(program), "-NoProfile", "-NonInteractive", "-Command", script],
        env=dict(
            os.environ,
            SEMANTIX_FIXTURE_ACL_PATH=str(path),
            PSModulePath=str(program.parent / "Modules"),
        ),
        capture_output=True,
        check=True,
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    acl: dict[str, Any] = json.loads(result.stdout)
    return acl


def private_directory() -> Path:
    root = Path(tempfile.mkdtemp(prefix="semantix-mysql-p5-"))
    if any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise RuntimeError("Fixture temporary directory must be outside Git worktrees")
    if os.name == "nt":
        system = Path(os.environ["SYSTEMROOT"]) / "System32"
        who = subprocess.run(  # noqa: S603 -- fixed Windows identity query
            [str(system / "whoami.exe"), "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            check=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        sid = who.stdout.rsplit(b",", 1)[-1].strip().strip(b'"').decode("ascii")
        if re.fullmatch(r"S-\d+(?:-\d+)+", sid) is None:
            raise RuntimeError("Cannot verify fixture Windows identity")
        subprocess.run(  # noqa: S603 -- restrict only this new empty directory before creating keys
            [
                str(system / "icacls.exe"),
                str(root),
                "/inheritance:r",
                "/grant:r",
                f"*{sid}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
                "*S-1-5-32-544:(OI)(CI)F",
            ],
            capture_output=True,
            check=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        acl = windows_acl(root)
        allowed = {sid, "S-1-5-18", "S-1-5-32-544"}
        if (
            not acl["protected"]
            or acl["owner"] not in allowed
            or any(
                # OWNER RIGHTS applies only to the verified owner.
                rule["type"] == "Allow" and rule["sid"] not in allowed | {"S-1-3-4"}
                for rule in acl["rules"]
            )
        ):
            raise RuntimeError("Fixture Windows directory ACL is not private")
    else:
        info = root.lstat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise RuntimeError("Fixture temporary directory is not private")
    return root


def private_write(path: Path, data: bytes, *, append: bool = False) -> None:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_EXCL)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "ab" if append else "wb") as stream:
        stream.write(data)


def redact(output: str, credential: str | None) -> str:
    return (
        output.replace(credential, "[redacted fixture credential]")
        if credential
        else output
    )


def diagnostic_text(output: str | bytes | None) -> str:
    """Windows may already have decoded a completed pipe when the other times out."""
    return (
        output.decode("utf8", errors="replace")
        if isinstance(output, bytes)
        else output or ""
    )


def public_command_output(output: str, credential: str | None, cwd: Path) -> str:
    """Bound permission-helper diagnostics without exporting keys or endpoints."""
    safe = redact(output, credential).replace(str(cwd), "[fixture directory]")
    safe = re.sub(
        r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----.*?(?:-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----|$)",
        "[redacted private key]",
        safe,
        flags=re.DOTALL,
    )
    safe = re.sub(
        r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"'<>]+", "[redacted endpoint]", safe
    )
    return safe[:4096] + ("[truncated]" if len(safe) > 4096 else "")


def command(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    credential: str | None = None,
    include_stderr: bool = False,
    phase: str | None = None,
    timeout: float = 90,
) -> str:
    if credential is None and env is not None:
        credential = env.get("MYSQL_ROOT_PASSWORD")
    started = time.monotonic()
    try:
        result = subprocess.run(  # noqa: S603 -- fixed tool argv and owned paths, no shell
            args,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as failure:
        code = None
        stdout = diagnostic_text(failure.stdout)
        stderr = diagnostic_text(failure.stderr)
    elapsed = round(time.monotonic() - started, 3)
    if phase is not None or code != 0:
        diagnostic: dict[str, Any] = {
            "phase": phase or "fixture command",
            "tool": Path(args[0]).name,
            "status": "timeout" if code is None else "failed" if code else "succeeded",
            "code": code,
            "elapsed_seconds": elapsed,
            "timeout_seconds": round(timeout, 3),
        }
        if phase is not None and code != 0:
            # Only credential-free permission commands opt into public stream output.
            diagnostic["stdout"] = public_command_output(stdout, credential, cwd)
            diagnostic["stderr"] = public_command_output(stderr, credential, cwd)
        print("Fixture command: " + json.dumps(diagnostic), file=sys.stderr, flush=True)
    if code != 0:
        private_write(
            cwd / "command-failures.jsonl",
            (
                json.dumps(
                    {
                        "args": [redact(arg, credential) for arg in args],
                        "code": code,
                        "phase": phase,
                        "elapsed_seconds": elapsed,
                        "stdout": redact(stdout, credential),
                        "stderr": redact(stderr, credential),
                    }
                )
                + "\n"
            ).encode("utf8"),
            append=True,
        )
        raise RuntimeError(
            "Disposable fixture command failed or timed out; sanitized output retained outside the repository"
        ) from None
    return (stdout + stderr if include_stderr else stdout).strip()


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


def connection(config: dict[str, Any], credential: str) -> Any:
    context = ssl.create_default_context(cafile=config["ca_file"])
    result = pymysql.Connection(
        host="localhost",
        port=config["port"],
        user="root",
        password=credential.encode("utf8"),
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
        info = root.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or root.is_symlink()
            or getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            or (root / "tls").exists()
        ):
            raise RuntimeError("Fixture requires a fresh owned temporary directory")
        self.root_identity = (info.st_dev, info.st_ino)
        self.tls = root / "tls"
        self.prepared = False
        private_write(
            root / "fixture.json",
            json.dumps({"owner": OWNER, "fixture_id": self.identifier}).encode("utf8"),
        )

    def prepare(self) -> None:
        self.tls = certificates(self.root)
        if os.name != "nt":
            # Only this freshly created TLS directory is changed, never developer data.
            permissions = f"semantix-mysql-p5-{self.identifier}-permissions"
            self.containers.append(permissions)
            deadline = time.monotonic() + 90
            command(
                [
                    "docker",
                    "create",
                    "--rm",
                    "--name",
                    permissions,
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
                    "chown 27:27 /tls/server-key.pem && chmod 755 /tls && chmod 600 /tls/server-key.pem && chmod 644 /tls/ca.pem /tls/server.pem /tls/expired.pem",
                ],
                cwd=self.root,
                phase="TLS permissions image acquisition/container creation",
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    "TLS permission preparation exhausted its 90-second budget before startup"
                )
            command(
                ["docker", "start", "--attach", permissions],
                cwd=self.root,
                phase="TLS permissions container startup/filesystem changes",
                timeout=remaining,
            )

        self.prepared = True

    def start(self, kind: str) -> dict[str, Any]:
        if not self.prepared:
            self.prepare()
        config: dict[str, Any] = {
            "fixture_owner": OWNER,
            "fixture_id": self.identifier,
            "address": "127.0.0.1",
            "tls_hostname": "localhost",
            "ca_file": str(self.tls / "ca.pem"),
            "untrusted_ca_file": str(self.tls / "untrusted-ca.pem"),
            "user": "root",
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
        self.containers.append(name)
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
                "--env",
                "MYSQL_ROOT_PASSWORD",
                "--env",
                "MYSQL_ROOT_HOST=%",
                "--tmpfs",
                "/var/lib/mysql-files:rw,noexec,nosuid,nodev,mode=0700,uid=27,gid=27",
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
            env=dict(os.environ, MYSQL_ROOT_PASSWORD=self.password),
        )
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
                    database = connection(config, self.password)
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
        info = self.root.lstat()
        marker = json.loads((self.root / "fixture.json").read_text())
        if (info.st_dev, info.st_ino) != self.root_identity or marker != {
            "owner": OWNER,
            "fixture_id": self.identifier,
        }:
            raise RuntimeError("Fixture directory ownership changed; refusing cleanup")
        for name in reversed(self.containers):
            existing = command(
                [
                    "docker",
                    "container",
                    "ls",
                    "--all",
                    "--filter",
                    f"name=^/{name}$",
                    "--format",
                    "{{.Names}}",
                ],
                cwd=self.root,
            )
            if not existing:
                continue
            if existing != name:
                raise RuntimeError(
                    "Unexpected fixture container identity; refusing cleanup"
                )
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
            logs = command(
                ["docker", "logs", name],
                cwd=self.root,
                credential=self.password,
                include_stderr=True,
            )
            private_write(
                self.root / (name + ".log"),
                redact(logs, self.password).encode("utf8"),
                append=True,
            )
            if not (self.root / (name + ".json")).exists():
                private_write(
                    self.root / (name + ".json"),
                    json.dumps(
                        {
                            "name": name,
                            "image": inspected["Image"],
                            "labels": labels,
                            "ports": inspected["HostConfig"]["PortBindings"],
                            "volumes": [
                                mount["Name"]
                                for mount in inspected["Mounts"]
                                if mount["Type"] == "volume"
                            ],
                        }
                    ).encode("utf8"),
                )
            command(["docker", "rm", name], cwd=self.root)
        for volume in self.volumes:
            inspected = json.loads(
                command(["docker", "volume", "inspect", volume], cwd=self.root)
            )[0]
            if (
                inspected["Labels"].get("semantix.fixture") != self.identifier
                or inspected["Labels"].get("semantix.owner") != OWNER
            ):
                raise RuntimeError("Fixture volume ownership changed; refusing cleanup")
        if self.tls.exists():
            if self.tls.is_symlink() or not self.tls.resolve().is_relative_to(
                self.root.resolve()
            ):
                raise RuntimeError(
                    "Fixture key directory ownership changed; refusing cleanup"
                )
            for filename in ("ca-key.pem", "untrusted-ca-key.pem", "server-key.pem"):
                (self.tls / filename).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    child = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not child:
        parser.error("A test command is required after --")
    root = private_directory()
    fixture = Fixture(root)
    try:
        valid = fixture.start("valid")
        valid["expired_port"] = fixture.start("expired")["port"]
        valid["no_tls_port"] = fixture.start("no_tls")["port"]
        receipt = root / "connection.json"
        private_write(receipt, json.dumps(valid).encode("utf8"))
        env = dict(
            os.environ,
            MYSQL_TEST_CONFIG=str(receipt),
            MYSQL_TEST_PASSWORD=fixture.password,
        )
        print("Disposable MySQL fixture ready: " + valid["server_version"], flush=True)
        try:
            result = subprocess.run(  # noqa: S603 -- explicit operator-supplied test argv, no shell
                child, env=env, capture_output=True, check=False, timeout=1800
            )
            code, stdout, stderr = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as failure:
            code, stdout, stderr = None, failure.stdout or b"", failure.stderr or b""
        for name, output in (("stdout", stdout), ("stderr", stderr)):
            safe_output = redact(
                output.decode("utf8", errors="replace"), fixture.password
            )
            private_write(root / ("child." + name + ".log"), safe_output.encode("utf8"))
            sys.stdout.write(safe_output)
        if code is None:
            raise RuntimeError(
                "Fixture child timed out; sanitized partial output retained"
            ) from None
        print("Fixture child exit: " + str(code), flush=True)
        return code
    finally:
        primary = sys.exception()
        try:
            fixture.close()
        except Exception as cleanup:
            if primary is not None:
                raise BaseExceptionGroup(
                    "Fixture failed and cleanup also failed", [primary, cleanup]
                ) from None
            raise
        print(
            "Owned containers removed; public diagnostics/data volumes retained at "
            + str(root),
            flush=True,
        )


if __name__ == "__main__":
    raise SystemExit(main())
