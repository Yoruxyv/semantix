"""Start the local dashboard safely; Python standard library and Docker only."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import closing
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from typing import cast
from urllib.parse import quote, unquote, urlsplit
from uuid import uuid4

OWNER = "com.semantix.dev-startup"
PROJECT = "com.docker.compose.project"
VOLUME = "com.docker.compose.volume"


class StartupError(Exception):
    """Fixed, secret-free CLI diagnostics."""


class Development:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.docker = shutil.which("docker")
        if self.docker is None:
            raise StartupError(
                "Install Docker with Compose and start its local engine."
            )
        self.compose = ["compose", "-f", str(self.root / "docker-compose.dev.yml")]
        self.model: dict[str, object] = {}
        self.project = ""
        self.lock = ""
        self.job = ""
        self.token = uuid4().hex
        self.stage = "preflight"
        self.context: str | None = None
        self.legacy_volumes: set[str] = set()

    def call(
        self, args: list[str], *, data: str | None = None, timeout: int = 60
    ) -> str:
        try:
            result = subprocess.run(  # noqa: S603 - absolute Docker executable, argument list, no shell
                [
                    cast(str, self.docker),
                    *(["--context", self.context] if self.context else []),
                    *args,
                ],
                cwd=self.root,
                input=data,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise StartupError(
                f"Development {self.stage} failed or exceeded its finite budget."
            ) from None
        if result.returncode:
            if self.stage == "configuration validation":
                raise StartupError(
                    "Invalid apps/server/.env: select memory, pgvector or redis, replace "
                    "required provider/storage placeholders, keep operator credentials "
                    "separate, and use DATABASE_MIGRATION_MODE=external for PostgreSQL."
                )
            raise StartupError(
                f"Development {self.stage} failed. Check Docker, configuration and existing "
                "storage; no automatic repair or retry is performed."
            )
        return result.stdout.strip()

    def objects(self, kind: str, name: str) -> list[dict[str, object]]:
        # Listing first distinguishes an absent object from an unavailable daemon.
        names = self.call(
            [
                kind,
                "ls",
                *(["-a"] if kind == "container" else []),
                "--format",
                "{{.Name}}" if kind == "volume" else "{{.Names}}",
            ]
        )
        if name not in names.splitlines():
            return []
        return cast(
            list[dict[str, object]], json.loads(self.call([kind, "inspect", name]))
        )

    def service(self, name: str) -> dict[str, object]:
        return cast(dict[str, dict[str, object]], self.model["services"])[name]

    def backend_environment(self) -> dict[str, str]:
        environment = cast(dict[str, str], self.service("backend")["environment"])
        return {name.upper(): value for name, value in environment.items()}

    def frontend_origin(self) -> str:
        for name in ("backend", "frontend", "postgres", "redis"):
            for mapping in cast(
                list[dict[str, object]], self.service(name).get("ports", [])
            ):
                if mapping.get("host_ip") != "127.0.0.1":
                    raise StartupError("Development ports must bind only to 127.0.0.1.")
        ports = cast(list[dict[str, object]], self.service("frontend")["ports"])
        port = int(str(ports[0]["published"]))
        origins = cast(
            list[str], json.loads(self.backend_environment()["ALLOWED_ORIGINS"])
        )
        for host in ("127.0.0.1", "localhost"):
            origin = f"http://{host}:{port}"
            if origin in {value.strip().rstrip("/") for value in origins}:
                return origin
        raise StartupError(
            "ALLOWED_ORIGINS must include the published frontend's loopback HTTP origin."
        )

    def config(self) -> dict[str, object]:
        return cast(
            dict[str, object],
            json.loads(
                self.call(
                    [*self.compose, "--profile", "*", "config", "--format", "json"]
                )
            ),
        )

    def check_config(self) -> None:
        if self.config() != self.model:
            raise StartupError(
                "Configuration changed during startup; inspect retained storage before recovery."
            )

    def verify_containers(self) -> None:
        identifiers = self.call(
            ["ps", "-aq", "--filter", f"label={PROJECT}={self.project}"]
        ).splitlines()
        for identifier in identifiers:
            info = cast(
                list[dict[str, object]], json.loads(self.call(["inspect", identifier]))
            )[0]
            config = cast(dict[str, object], info["Config"])
            labels = cast(dict[str, str], config["Labels"])
            working = labels.get("com.docker.compose.project.working_dir")
            config_file = labels.get("com.docker.compose.project.config_files")
            allowed = {
                self.root / "docker-compose.dev.yml",
                self.root / "docker-compose.yml",
            }
            if (
                working is None
                or Path(working).resolve() != self.root
                or config_file is None
                or Path(config_file).resolve() not in allowed
            ):
                raise StartupError(
                    "This Compose project is not verified development infrastructure for "
                    "this checkout; inspect its ownership and configuration."
                )
            service = labels.get("com.docker.compose.service")
            target = {"postgres": "/var/lib/postgresql/data", "redis": "/data"}.get(
                service or ""
            )
            if target is not None:
                mounts = cast(list[dict[str, str]], info["Mounts"])
                self.legacy_volumes.update(
                    mount["Name"]
                    for mount in mounts
                    if mount.get("Type") == "volume"
                    and mount.get("Destination") == target
                )

    def volume(self, alias: str) -> bool:
        specification = cast(dict[str, dict[str, object]], self.model["volumes"])[alias]
        name = str(specification["name"])
        if name != f"{self.project}_{alias}" or specification.get("external"):
            raise StartupError(
                "Only the project's default local development volumes can be managed."
            )
        existing = self.objects("volume", name)
        if not existing:
            self.call(
                [
                    "volume",
                    "create",
                    "--label",
                    f"{PROJECT}={self.project}",
                    "--label",
                    f"{VOLUME}={alias}",
                    "--label",
                    f"{OWNER}={self.token}",
                    "--label",
                    f"{OWNER}.checkout={self.root}",
                    name,
                ]
            )
            created = self.objects("volume", name)
            if (
                not created
                or cast(dict[str, str], created[0].get("Labels") or {}).get(OWNER)
                != self.token
            ):
                raise StartupError(
                    "Volume creation ownership could not be established."
                )
            existing = created
            fresh = True
        else:
            fresh = False
        item = existing[0]
        labels = cast(dict[str, str], item.get("Labels") or {})
        if (
            labels.get(PROJECT) != self.project
            or labels.get(VOLUME) != alias
            or item.get("Driver") != "local"
            or item.get("Options")
        ):
            raise StartupError(
                "Existing volume ownership/driver is not recognized; explicit operator review is required."
            )
        if not fresh and name not in self.legacy_volumes:
            marker = labels.get(OWNER, "")
            checkout = labels.get(f"{OWNER}.checkout")
            if re.fullmatch(r"[a-f0-9]{32}", marker) is None or checkout != str(
                self.root
            ):
                raise StartupError(
                    "Existing volume lacks verified development provenance. Review it "
                    "with its original Compose configuration before explicit recovery."
                )
        return fresh

    def helper(self, phase: str, fresh: dict[str, bool] | None = None) -> str:
        self.stage = (
            "configuration validation"
            if phase == "check"
            else "storage setup/validation"
        )
        self.job = f"{self.project}-dev-setup-{self.token}"
        receipt: dict[str, object] | None = None
        if fresh is not None:
            migration_url = None
            if fresh["postgres"]:
                operator = cast(dict[str, str], self.service("postgres")["environment"])
                migration_url = (
                    "postgresql://"
                    + quote(operator["POSTGRES_USER"], safe="")
                    + ":"
                    + quote(operator["POSTGRES_PASSWORD"], safe="")
                    + "@postgres:5432/"
                    + quote(operator["POSTGRES_DB"], safe="")
                )
            receipt = {**fresh, "migration_url": migration_url}
        return self.call(
            [
                *self.compose,
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "--name",
                self.job,
                "--label",
                f"{OWNER}={self.token}",
                "backend",
                "python",
                "-m",
                "scripts.dev_storage",
                phase,
            ],
            data=json.dumps(receipt) if receipt is not None else None,
            timeout=180,
        )

    def container(self, service: str) -> str:
        identifier = self.call([*self.compose, "ps", "-q", service])
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise StartupError(
                "Expected exactly one owned development service container."
            )
        return identifier

    def provision_role(self) -> None:
        self.stage = "PostgreSQL role provisioning"
        environment = self.backend_environment()
        parsed = urlsplit(environment["DATABASE_URL"])
        role, password = unquote(parsed.username or ""), unquote(parsed.password or "")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", role) is None or any(
            c in password for c in "\r\n\x00"
        ):
            raise StartupError(
                "Runtime credentials are invalid for safe local provisioning."
            )
        # psql hashes \password input before sending ALTER ROLE; no plaintext SQL/argv.
        script = (
            "BEGIN;\n"  # noqa: S608 - ASCII-validated role; password is psql prompt input, never SQL
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname "
            "!~ '^pg_' AND nspname NOT IN ('public','information_schema')) "
            "OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public') "
            "THEN RAISE EXCEPTION 'Nonempty database requires explicit setup'; END IF; END $$;\n"
            f'CREATE ROLE "{role}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
            "NOREPLICATION NOBYPASSRLS NOINHERIT;\n"
            f'\\password "{role}"\n{password}\n{password}\nCOMMIT;\n'
        )
        operator = cast(dict[str, str], self.service("postgres")["environment"])
        if any(c in operator["POSTGRES_PASSWORD"] for c in "\r\n\x00"):
            raise StartupError("Bootstrap password cannot contain psql control input.")
        network = f"{self.project}_default"
        labels = cast(
            dict[str, str],
            json.loads(
                self.call(
                    ["network", "inspect", "--format", "{{json .Labels}}", network]
                )
            ),
        )
        if (
            labels.get(PROJECT) != self.project
            or labels.get("com.docker.compose.network") != "default"
        ):
            raise StartupError(
                "Development setup network ownership could not be verified."
            )
        self.job = f"{self.project}-dev-role-{self.token}"
        self.call(
            [
                "run",
                "--rm",
                "-i",
                "--name",
                self.job,
                "--label",
                f"{OWNER}={self.token}",
                "--label",
                f"{PROJECT}={self.project}",
                "--label",
                f"com.docker.compose.project.working_dir={self.root}",
                "--label",
                f"com.docker.compose.project.config_files={self.root / 'docker-compose.dev.yml'}",
                "--network",
                network,
                "--read-only",
                "--tmpfs",
                "/var/lib/postgresql/data",
                "--entrypoint",
                "psql",
                str(self.service("postgres")["image"]),
                "-X",
                "-W",
                "--set",
                "ON_ERROR_STOP=1",
                "--host",
                "postgres",
                "--username",
                operator["POSTGRES_USER"],
                "--dbname",
                operator["POSTGRES_DB"],
            ],
            data=operator["POSTGRES_PASSWORD"] + "\n" + script,
        )

    def endpoint(self, service: str, target: int) -> str:
        info = cast(
            list[dict[str, object]],
            json.loads(self.call(["inspect", self.container(service)])),
        )[0]
        network = cast(dict[str, object], info["NetworkSettings"])
        mappings = cast(dict[str, list[dict[str, str]]], network["Ports"])[
            f"{target}/tcp"
        ]
        if len(mappings) != 1 or mappings[0]["HostIp"] != "127.0.0.1":
            raise StartupError(
                "Development services must publish exactly one loopback endpoint."
            )
        return f"http://127.0.0.1:{int(mappings[0]['HostPort'])}"

    @staticmethod
    def wait_http(url: str, *, ready: bool) -> None:
        deadline = time.monotonic() + 60
        parsed = urlsplit(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.port is None
        ):
            raise StartupError("Readiness requires a verified loopback HTTP endpoint.")
        while time.monotonic() < deadline:
            try:
                with closing(
                    HTTPConnection("127.0.0.1", parsed.port, timeout=2)
                ) as connection:
                    connection.request("GET", parsed.path or "/")
                    response = connection.getresponse()
                    if response.status == 200 and (
                        not ready
                        or json.loads(response.read(4096)).get("status") == "ready"
                    ):
                        return
            except (HTTPException, OSError):
                pass
            # Readiness polling never replays a business operation or initialization.
            time.sleep(0.25)
        raise StartupError(
            "Service readiness failed; the frontend was not declared ready."
        )

    def cleanup(self) -> None:
        if self.job:
            jobs = self.objects("container", self.job)
            if jobs:
                config = cast(dict[str, object], jobs[0]["Config"])
                labels = cast(dict[str, str], config["Labels"])
                if (
                    labels.get(PROJECT) != self.project
                    or labels.get(OWNER) != self.token
                ):
                    raise StartupError(
                        "Setup-job ownership is uncertain; startup lock retained."
                    )
                identifier = str(jobs[0]["Id"])
                self.call(
                    ["stop", "--signal", "SIGINT", "--timeout", "10", identifier],
                    timeout=20,
                )
                remaining = self.objects("container", self.job)
                if remaining:
                    if cast(dict[str, object], remaining[0]["State"])["Running"]:
                        raise StartupError(
                            "Setup job is still running; startup lock retained."
                        )
                    self.call(["rm", identifier])
        if self.lock:
            self.call(["rm", self.lock])
            self.lock = ""

    def check_docker(self) -> None:
        if os.environ.get("DOCKER_HOST"):
            raise StartupError(
                "Unset DOCKER_HOST and select a local Docker Engine/Desktop context."
            )
        self.context = self.call(["context", "show"])
        if not self.context:
            raise StartupError("Select a local Docker context before startup.")
        endpoint = self.call(
            [
                "context",
                "inspect",
                self.context,
                "--format",
                '{{(index .Endpoints "docker").Host}}',
            ]
        )
        if not endpoint.startswith(("unix://", "npipe://")):
            raise StartupError(
                "Use a local Docker Engine/Desktop context; remote Docker provisioning is unsupported."
            )
        versions = self.call(
            ["version", "--format", "{{.Client.APIVersion}} {{.Server.APIVersion}}"]
        ).split()
        override = os.environ.get("DOCKER_API_VERSION")
        if override:
            versions.append(override)
        if (
            len(versions) < 2
            or any(
                re.fullmatch(r"[0-9]+\.[0-9]+", version) is None for version in versions
            )
            or any(
                tuple(int(part) for part in version.split(".")) < (1, 42)
                for version in versions
            )
            or "--signal" not in self.call(["stop", "--help"])
        ):
            raise StartupError(
                "Use Docker CLI/Engine 23+ (API 1.42+) for bounded setup cancellation."
            )

    def up(self) -> None:
        if not (self.root / "apps/server/.env").is_file():
            raise StartupError(
                "Create untracked apps/server/.env from .env.example, then configure providers and storage."
            )
        self.check_docker()
        self.model = self.config()
        self.project = str(self.model["name"])
        if (
            re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,50}", self.project) is None
            or self.project == "semantix-prod"
        ):
            raise StartupError(
                "Use a development COMPOSE_PROJECT_NAME, distinct from production."
            )
        self.verify_containers()
        sys.stdout.write(
            "Building development images (first use can download dependencies)...\n"
        )
        self.stage = "image build"
        self.call([*self.compose, "build", "backend", "frontend"], timeout=1200)
        image = str(self.service("backend").get("image", f"{self.project}-backend"))
        self.stage = (
            "startup-lock acquisition (another invocation or retained lock may exist)"
        )
        self.lock = self.call(
            [
                "create",
                "--name",
                f"{self.project}-dev-startup-lock",
                "--label",
                f"{OWNER}={self.token}",
                "--label",
                f"{OWNER}.project={self.project}",
                "--label",
                f"{OWNER}.checkout={self.root}",
                "--network",
                "none",
                image,
                "python",
                "-c",
                "pass",
            ]
        )
        if not re.fullmatch(r"[a-f0-9]{64}", self.lock):
            raise StartupError("Could not acquire startup lock.")
        try:
            selected = cast(dict[str, bool], json.loads(self.helper("check")))
            if set(selected) != {"postgres", "redis"} or any(
                type(value) is not bool for value in selected.values()
            ):
                raise StartupError("Invalid setup plan.")
            self.check_config()
            origin = self.frontend_origin()
            fresh = {"postgres": False, "redis": False}
            for service, alias in (
                ("postgres", "pgvector_data"),
                ("redis", "redis_data"),
            ):
                if selected[service]:
                    self.stage = "local database readiness"
                    fresh[service] = self.volume(alias)
                    self.call(
                        [
                            *self.compose,
                            "--profile",
                            "pgvector" if service == "postgres" else "redis",
                            "up",
                            "--no-deps",
                            "-d",
                            "--wait",
                            "--wait-timeout",
                            "90",
                            service,
                        ],
                        timeout=120,
                    )
                    # Verify the selected database actually uses the expected owned volume.
                    info = cast(
                        list[dict[str, object]],
                        json.loads(self.call(["inspect", self.container(service)])),
                    )[0]
                    mounts = cast(list[dict[str, str]], info["Mounts"])
                    volume = cast(dict[str, dict[str, str]], self.model["volumes"])[
                        alias
                    ]["name"]
                    target = (
                        "/var/lib/postgresql/data" if service == "postgres" else "/data"
                    )
                    if not any(
                        m.get("Name") == volume and m.get("Destination") == target
                        for m in mounts
                    ):
                        raise StartupError(
                            "Database volume mount ownership did not match."
                        )
            self.check_config()
            if fresh["postgres"]:
                self.provision_role()
            sys.stdout.write(
                "Preparing fresh owned storage; validating existing storage without repair...\n"
            )
            self.helper("setup", fresh)
            self.check_config()
            self.stage = "application readiness"
            self.call(
                [
                    *self.compose,
                    "up",
                    "--no-deps",
                    "-d",
                    "--wait",
                    "--wait-timeout",
                    "90",
                    "backend",
                ],
                timeout=120,
            )
            self.wait_http(self.endpoint("backend", 8000) + "/ready", ready=True)
            self.stage = "application readiness"
            self.call(
                [
                    *self.compose,
                    "up",
                    "--no-deps",
                    "-d",
                    "--wait",
                    "--wait-timeout",
                    "90",
                    "frontend",
                ],
                timeout=120,
            )
            frontend = self.endpoint("frontend", 4173)
            self.wait_http(frontend, ready=False)
            sys.stdout.write(f"Dashboard ready: {origin}\n")
        finally:
            primary = sys.exception()
            try:
                self.stage = "owned setup-job cleanup"
                self.cleanup()
            except StartupError:
                if primary is not None:
                    raise StartupError(
                        "Startup and cleanup both failed; verify the retained setup job "
                        "and startup lock before explicit recovery. Storage was retained."
                    ) from None
                raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["up"])
    parser.parse_args()
    if not (3, 11) <= sys.version_info[:2] < (3, 15):
        sys.stderr.write("Use Python 3.11-3.14 for this development launcher.\n")
        return 1
    try:
        Development(Path(__file__).resolve().parents[1]).up()
    except (StartupError, KeyboardInterrupt) as error:
        sys.stderr.write(
            (
                str(error)
                if isinstance(error, StartupError)
                else "Startup interrupted; inspect partial setup before retrying."
            )
            + "\nExisting storage was retained. Check for an unfinished setup job/startup lock before recovery.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
