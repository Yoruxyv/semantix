"""Verify a pgvector cache round trip through a disposable dump and restore."""

import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from phase13 import ROOT, api, command, compose, direct, environment


def wait_ready(env: dict[str, str]) -> None:
    for _ in range(60):
        try:
            if (
                all(
                    direct(env, service, "/ready")[0] == 200
                    for service in ("backend-a", "backend-b")
                )
                and api(env, "/ready")[0] == 200
            ):
                return
        except (RuntimeError, ValueError):
            pass
        time.sleep(1)
    raise AssertionError("Gateway and both replicas did not regain readiness")


def main() -> None:
    admin, operator = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    name = uuid4().hex[:8]
    source = f"semantix-audit-backup-{name}"
    restored = f"semantix-audit-restore-{name}"
    for project in (source, restored):
        assert not command(
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            "{{.ID}}",
            env=os.environ,
        ).strip(), project

    with tempfile.TemporaryDirectory(prefix="phase13-backup-", dir=ROOT) as temporary:
        folder = Path(temporary)
        upstream = folder / "upstream.conf"
        upstream.write_text(
            (ROOT / "frontend/upstream.prod.conf").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        dump = folder / "semantix.dump"
        source_env = environment(source, upstream, admin, operator)
        restored_env = source_env | {"COMPOSE_PROJECT_NAME": restored}
        source_started = restored_started = False
        try:
            source_started = True
            compose(
                source_env, "up", "--build", "-d", "--wait", "--wait-timeout", "240"
            )
            prompt = f"backup-restore-{uuid4().hex}"
            payload = {"prompt": prompt, "namespace": "phase13"}
            first_status, first = api(
                source_env, "/api/v1/query", token=admin, method="POST", payload=payload
            )
            assert first_status == 200 and first["provider_called"] is True

            compose(source_env, "restart", "backend-a", "backend-b", "frontend")
            wait_ready(source_env)
            restarted_status, restarted = api(
                source_env, "/api/v1/query", token=admin, method="POST", payload=payload
            )
            assert restarted_status == 200 and restarted["cache_hit"] is True

            compose(source_env, "stop", "postgres")
            outage_started = time.monotonic()
            outage_ready = int(
                compose(
                    source_env,
                    "exec",
                    "-T",
                    "frontend",
                    "curl",
                    "-sS",
                    "--max-time",
                    "40",
                    "-w",
                    "\n%{http_code}",
                    "http://backend-a:8000/ready",
                ).rsplit("\n", 1)[1]
            )
            outage_ready_ms = round((time.monotonic() - outage_started) * 1000)
            assert outage_ready == 503, outage_ready
            compose(source_env, "start", "postgres")
            wait_ready(source_env)

            source_container = compose(source_env, "ps", "-q", "postgres").strip()
            migrator = source_env["POSTGRES_MIGRATION_USER"]
            database = source_env["POSTGRES_DB"]
            password = source_env["POSTGRES_MIGRATION_PASSWORD"]
            compose(
                source_env,
                "exec",
                "-T",
                "-e",
                f"PGPASSWORD={password}",
                "postgres",
                "pg_dump",
                "--host",
                "127.0.0.1",
                "--username",
                migrator,
                "--dbname",
                database,
                "--format",
                "custom",
                "--no-owner",
                "--no-acl",
                "--file",
                "/tmp/semantix.dump",
            )
            command(
                "docker",
                "cp",
                f"{source_container}:/tmp/semantix.dump",
                str(dump),
                env=source_env,
            )
            assert dump.stat().st_size > 0
            compose(source_env, "down", "--volumes", "--remove-orphans")
            source_started = False

            restored_started = True
            compose(
                restored_env, "up", "-d", "--wait", "--wait-timeout", "120", "postgres"
            )
            target_container = compose(restored_env, "ps", "-q", "postgres").strip()
            command(
                "docker",
                "cp",
                str(dump),
                f"{target_container}:/tmp/semantix.dump",
                env=restored_env,
            )
            compose(
                restored_env,
                "exec",
                "-T",
                "-e",
                f"PGPASSWORD={password}",
                "postgres",
                "pg_restore",
                "--host",
                "127.0.0.1",
                "--username",
                migrator,
                "--dbname",
                database,
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
                "/tmp/semantix.dump",
            )
            compose(
                restored_env, "up", "--build", "-d", "--wait", "--wait-timeout", "240"
            )
            second_status, second = api(
                restored_env,
                "/api/v1/query",
                token=admin,
                method="POST",
                payload=payload,
            )
            assert second_status == 200 and second["cache_hit"] is True
            print(
                json.dumps(
                    {
                        "source_provider_called": first["provider_called"],
                        "restart_cache_hit": restarted["cache_hit"],
                        "outage_ready": outage_ready,
                        "outage_ready_ms": outage_ready_ms,
                        "restored_cache_hit": second["cache_hit"],
                        "dump_bytes": dump.stat().st_size,
                        "restored_ready": api(restored_env, "/ready")[0],
                    }
                )
            )
        finally:
            if source_started:
                compose(source_env, "down", "--volumes", "--remove-orphans")
            if restored_started:
                compose(restored_env, "down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
