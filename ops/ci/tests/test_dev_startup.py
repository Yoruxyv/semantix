"""Development orchestration boundaries; no Docker resources are needed."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.dev import OWNER, PROJECT, VOLUME, Development, StartupError


@pytest.fixture
def launcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Development:
    monkeypatch.setattr("scripts.dev.shutil.which", lambda name: "docker")
    active = Development(tmp_path)
    active.project = "semantix-test"
    active.model = {
        "name": active.project,
        "volumes": {"pgvector_data": {"name": "semantix-test_pgvector_data"}},
        "services": {
            "frontend": {"ports": [{"host_ip": "127.0.0.1", "published": "4173"}]},
            "redis": {},
            "postgres": {
                "image": "owned-postgres-image",
                "environment": {
                    "POSTGRES_USER": "fixture_bootstrap",
                    "POSTGRES_PASSWORD": "fixture-operator",
                    "POSTGRES_DB": "semantix",
                },
            },
            "backend": {
                "environment": {
                    "ALLOWED_ORIGINS": '["http://localhost:4173"]',
                    "DATABASE_URL": "postgresql://semantix_runtime:fixture-value@postgres/semantix",
                }
            },
        },
    }
    return active


def test_existing_volume_is_validation_only(
    launcher: Development, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = {
        "Driver": "local",
        "Options": {},
        "Labels": {PROJECT: launcher.project, VOLUME: "pgvector_data"},
    }
    launcher.legacy_volumes.add("semantix-test_pgvector_data")
    monkeypatch.setattr(launcher, "objects", lambda kind, name: [item])
    assert launcher.volume("pgvector_data") is False


@pytest.mark.parametrize(
    "changes",
    [{"Labels": {}}, {"Driver": "nfs"}, {"Options": {"device": "/developer-data"}}],
)
def test_unrecognized_volume_is_never_adopted(
    launcher: Development, monkeypatch: pytest.MonkeyPatch, changes: dict[str, object]
) -> None:
    item = {
        "Driver": "local",
        "Options": {},
        "Labels": {PROJECT: launcher.project, VOLUME: "pgvector_data"},
    }
    item.update(changes)
    monkeypatch.setattr(launcher, "objects", lambda kind, name: [item])
    with pytest.raises(StartupError, match="ownership/driver"):
        launcher.volume("pgvector_data")


def test_racing_volume_creation_is_refused(
    launcher: Development, monkeypatch: pytest.MonkeyPatch
) -> None:
    observations = iter([[], [{"Labels": {OWNER: "another-owner"}}]])
    monkeypatch.setattr(launcher, "objects", lambda kind, name: next(observations))
    monkeypatch.setattr(launcher, "call", lambda args, **kwargs: "unused")
    with pytest.raises(StartupError, match="creation ownership"):
        launcher.volume("pgvector_data")


def test_docker_failure_output_cannot_expose_credentials(
    launcher: Development, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            ["docker"], 1, "private-fixture-value", "private-endpoint"
        )

    monkeypatch.setattr(subprocess, "run", failed)
    with pytest.raises(StartupError) as caught:
        launcher.call(["version"])
    assert "private" not in str(caught.value)


def test_subprocess_timeout_is_bounded_and_sanitized(
    launcher: Development, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(
            "private-fixture-value", 60, output="private-endpoint"
        )

    monkeypatch.setattr(subprocess, "run", failed)
    with pytest.raises(StartupError, match="finite budget") as caught:
        launcher.call(["version"])
    assert "private" not in str(caught.value)


def test_role_password_goes_only_to_psql_stdin(
    launcher: Development, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], str]] = []
    monkeypatch.setattr(launcher, "container", lambda service: "a" * 64)

    def observe(args: list[str], *, data: str | None = None, **kwargs: object) -> str:
        if args[0] == "network":
            return json.dumps(
                {PROJECT: launcher.project, "com.docker.compose.network": "default"}
            )
        calls.append((args, data or ""))
        return ""

    monkeypatch.setattr(launcher, "call", observe)
    launcher.provision_role()
    args, data = calls[0]
    assert "fixture-value" not in " ".join(args)
    assert '\\password "semantix_runtime"\nfixture-value\nfixture-value\n' in data
    assert "PASSWORD 'fixture-value'" not in data
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE" in data
    assert data.startswith("fixture-operator\nBEGIN;")
    assert "fixture-operator" not in " ".join(args)
    assert "--read-only" in args
    assert "--entrypoint" in args
    assert "psql" in args
    assert "--mount" not in args
    assert "--volume" not in args
    assert data.endswith("COMMIT;\n")


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://bad%22role:fixture@postgres/semantix",
        "postgresql://runtime:bad%0Ainput@postgres/semantix",
    ],
)
def test_psql_control_input_is_rejected(launcher: Development, url: str) -> None:
    launcher.model["services"] = {"backend": {"environment": {"DATABASE_URL": url}}}
    with pytest.raises(StartupError, match="invalid"):
        launcher.provision_role()


def test_foreign_setup_job_retains_lock(
    launcher: Development, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher.job, launcher.lock = "test-job", "lock-id"
    monkeypatch.setattr(
        launcher,
        "objects",
        lambda kind, name: [
            {"Config": {"Labels": {PROJECT: launcher.project, OWNER: "foreign"}}}
        ],
    )
    with pytest.raises(StartupError, match="ownership"):
        launcher.cleanup()
    assert launcher.lock == "lock-id"


def test_cleanup_stops_owned_job_before_releasing_lock(
    launcher: Development, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher.job, launcher.lock = "test-job", "lock-id"
    job = {
        "Id": "job-id",
        "Config": {"Labels": {PROJECT: launcher.project, OWNER: launcher.token}},
        "State": {"Running": False},
    }
    monkeypatch.setattr(launcher, "objects", lambda kind, name: [job])
    calls: list[list[str]] = []

    def record(args: list[str], **kwargs: object) -> str:
        calls.append(args)
        return ""

    monkeypatch.setattr(launcher, "call", record)
    launcher.cleanup()
    assert calls == [
        ["stop", "--signal", "SIGINT", "--timeout", "10", "job-id"],
        ["rm", "job-id"],
        ["rm", "lock-id"],
    ]
    assert not launcher.lock


def test_missing_configuration_never_calls_docker(launcher: Development) -> None:
    with pytest.raises(StartupError, match="Create untracked"):
        launcher.up()


def test_failed_setup_never_starts_backend_or_frontend(
    launcher: Development, monkeypatch: pytest.MonkeyPatch
) -> None:
    (launcher.root / "apps/server").mkdir(parents=True)
    (launcher.root / "apps/server/.env").touch()
    monkeypatch.setattr(launcher, "config", lambda: launcher.model)
    monkeypatch.setattr(launcher, "verify_containers", lambda: None)
    monkeypatch.setattr(launcher, "cleanup", lambda: None)
    calls: list[list[str]] = []

    def record(args: list[str], **kwargs: object) -> str:
        calls.append(args)
        if args[0] == "context":
            return "unix:///docker.sock"
        if args[0] == "version":
            return "1.56 1.56"
        if args[:2] == ["stop", "--help"]:
            return "--signal"
        return "a" * 64

    def helper(phase: str, fresh: dict[str, bool] | None = None) -> str:
        if phase == "check":
            return json.dumps({"postgres": False, "redis": False})
        raise StartupError("injected setup failure")

    monkeypatch.setattr(launcher, "call", record)
    monkeypatch.setattr(launcher, "helper", helper)
    with pytest.raises(StartupError, match="injected"):
        launcher.up()
    assert not any("up" in args for args in calls)


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "http://example.invalid/ready", "https://127.0.0.1/ready"],
)
def test_readiness_refuses_unverified_endpoints(url: str) -> None:
    with pytest.raises(StartupError, match="loopback"):
        Development.wait_http(url, ready=True)


@pytest.mark.parametrize(
    "override", ["tcp://remote.example:2375", "unix:///another-engine.sock"]
)
def test_docker_host_override_cannot_bypass_local_context(
    launcher: Development, monkeypatch: pytest.MonkeyPatch, override: str
) -> None:
    (launcher.root / "apps/server").mkdir(parents=True)
    (launcher.root / "apps/server/.env").touch()
    monkeypatch.setenv("DOCKER_HOST", override)
    with pytest.raises(StartupError, match="Unset DOCKER_HOST"):
        launcher.up()


def test_configuration_changes_stop_before_more_work(
    launcher: Development, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(launcher, "config", lambda: {"name": "changed"})
    with pytest.raises(StartupError, match="Configuration changed"):
        launcher.check_config()


def test_cleanup_failure_retains_lock(
    launcher: Development, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher.job, launcher.lock = "test-job", "lock-id"
    job = {
        "Id": "job-id",
        "Config": {"Labels": {PROJECT: launcher.project, OWNER: launcher.token}},
    }
    monkeypatch.setattr(launcher, "objects", lambda kind, name: [job])

    def fail(args: list[str], **kwargs: object) -> str:
        raise StartupError("injected stop failure")

    monkeypatch.setattr(launcher, "call", fail)
    with pytest.raises(StartupError, match="injected"):
        launcher.cleanup()
    assert launcher.lock == "lock-id"


@pytest.mark.parametrize("version", ["1.41 1.56", "1.56 1.41", "malformed"])
def test_old_or_invalid_docker_api_stops_before_provisioning(
    launcher: Development, monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    def inspect(args: list[str], **kwargs: object) -> str:
        if args[:2] == ["context", "show"]:
            return "desktop-linux"
        if args[0] == "context":
            return "unix:///docker.sock"
        if args[0] == "version":
            return version
        return "--signal"

    monkeypatch.setattr(launcher, "call", inspect)
    with pytest.raises(StartupError, match=r"API 1\.42"):
        launcher.check_docker()


def test_selected_docker_context_is_fixed_for_subprocesses(
    launcher: Development, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher.context = "verified-local"
    calls: list[list[str]] = []

    def observe(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", observe)
    launcher.call(["version"])
    assert calls[0][:3] == ["docker", "--context", "verified-local"]


def test_browser_origin_must_match_published_frontend(launcher: Development) -> None:
    assert launcher.frontend_origin() == "http://localhost:4173"
    launcher.service("frontend")["ports"] = [
        {"host_ip": "127.0.0.1", "published": "14173"}
    ]
    with pytest.raises(StartupError, match="ALLOWED_ORIGINS"):
        launcher.frontend_origin()


def test_compose_labels_alone_cannot_adopt_an_unproven_volume(
    launcher: Development, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = {
        "Driver": "local",
        "Options": {},
        "Labels": {PROJECT: launcher.project, VOLUME: "pgvector_data"},
    }
    monkeypatch.setattr(launcher, "objects", lambda kind, name: [item])
    with pytest.raises(StartupError, match="provenance"):
        launcher.volume("pgvector_data")


def test_owned_volume_can_restart_after_containers_are_removed(
    launcher: Development, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = {
        "Driver": "local",
        "Options": {},
        "Labels": {
            PROJECT: launcher.project,
            VOLUME: "pgvector_data",
            OWNER: "a" * 32,
            f"{OWNER}.checkout": str(launcher.root),
        },
    }
    monkeypatch.setattr(launcher, "objects", lambda kind, name: [item])
    assert launcher.volume("pgvector_data") is False


def test_production_compose_cannot_be_adopted_by_project_name(
    launcher: Development, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = {
        "Config": {
            "Labels": {
                PROJECT: launcher.project,
                "com.docker.compose.project.working_dir": str(launcher.root),
                "com.docker.compose.project.config_files": str(
                    launcher.root / "docker-compose.prod.yml"
                ),
            }
        }
    }

    def inspect(args: list[str], **kwargs: object) -> str:
        return "a" * 64 if args[0] == "ps" else json.dumps([info])

    monkeypatch.setattr(launcher, "call", inspect)
    with pytest.raises(StartupError, match="not verified development"):
        launcher.verify_containers()


def test_verified_legacy_database_mount_establishes_development_provenance(
    launcher: Development, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = {
        "Config": {
            "Labels": {
                PROJECT: launcher.project,
                "com.docker.compose.project.working_dir": str(launcher.root),
                "com.docker.compose.project.config_files": str(
                    launcher.root / "docker-compose.yml"
                ),
                "com.docker.compose.service": "postgres",
            }
        },
        "Mounts": [
            {
                "Type": "volume",
                "Destination": "/var/lib/postgresql/data",
                "Name": "semantix-test_pgvector_data",
            }
        ],
    }

    def inspect(args: list[str], **kwargs: object) -> str:
        return "a" * 64 if args[0] == "ps" else json.dumps([info])

    monkeypatch.setattr(launcher, "call", inspect)
    launcher.verify_containers()
    assert launcher.legacy_volumes == {"semantix-test_pgvector_data"}
