"""Credential handoff, private files and owned disposal without a Docker daemon."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

spec = importlib.util.spec_from_file_location(
    "mysql_fixture", Path(__file__).resolve().parents[1] / "mysql_fixture.py"
)
assert spec is not None
assert spec.loader is not None
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def test_private_directory_and_exclusive_file_permissions() -> None:
    root = fixture.private_directory()
    target = root / "permission-probe"
    fixture.private_write(target, b"non-secret permission probe")
    with pytest.raises(FileExistsError):
        fixture.private_write(target, b"must not overwrite")
    assert target.read_bytes() == b"non-secret permission probe"
    if os.name == "nt":
        parent = fixture.windows_acl(root)
        child = fixture.windows_acl(target)
        assert parent["protected"]
        assert not child["protected"]
        assert child["owner"] == parent["owner"]
        allowed = {parent["owner"], "S-1-5-18", "S-1-5-32-544", "S-1-3-4"}
        for acl in (parent, child):
            assert acl["rules"]
            assert all(
                r["sid"] in allowed for r in acl["rules"] if r["type"] == "Allow"
            )
    else:
        assert root.stat().st_uid == os.getuid()
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    target.unlink()
    root.rmdir()


def test_git_temporary_root_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").touch()
    root = tmp_path / "fixture"
    root.mkdir()
    monkeypatch.setattr(fixture.tempfile, "mkdtemp", lambda **kwargs: str(root))
    with pytest.raises(RuntimeError, match="outside Git"):
        fixture.private_directory()
    assert not list(root.iterdir())


def test_existing_tls_directory_is_not_owned(tmp_path: Path) -> None:
    (tmp_path / "tls").mkdir()
    with pytest.raises(RuntimeError, match="fresh owned"):
        fixture.Fixture(tmp_path)
    assert not (tmp_path / "fixture.json").exists()


@pytest.mark.parametrize("timeout", [False, True])
def test_command_failure_sanitizes_both_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, timeout: bool
) -> None:
    owned = fixture.Fixture(tmp_path)

    def failed(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert owned.password not in " ".join(args)
        if timeout:
            raise subprocess.TimeoutExpired(
                args, 90, output=owned.password.encode(), stderr=b"server diagnostic"
            )
        return subprocess.CompletedProcess(args, 1, owned.password, "server diagnostic")

    monkeypatch.setattr(fixture.subprocess, "run", failed)
    with pytest.raises(RuntimeError, match="sanitized output"):
        fixture.command(
            ["docker", "create"],
            cwd=tmp_path,
            env={"MYSQL_ROOT_PASSWORD": owned.password},
        )
    content = (tmp_path / "command-failures.jsonl").read_text()
    assert owned.password not in content
    diagnostic = json.loads(content)
    assert diagnostic["stdout"] == "[redacted fixture credential]"
    assert diagnostic["stderr"] == "server diagnostic"
    assert diagnostic["code"] == (None if timeout else 1)


@pytest.mark.parametrize("server_version", ["8.4.11", "8.4.12"])
@pytest.mark.parametrize("lost_ack", [False, True])
def test_start_uses_environment_and_tracks_uncertain_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lost_ack: bool, server_version: str
) -> None:
    owned = fixture.Fixture(tmp_path, server_version)
    owned.prepared = True
    calls: list[tuple[list[str], dict[str, object]]] = []

    def command(args: list[str], **kwargs: object) -> str:
        calls.append((args, kwargs))
        assert owned.password not in " ".join(args)
        assert "--env-file" not in args
        if args[:2] == ["docker", "create"]:
            assert fixture.IMAGES[server_version] in args
            assert args[args.index("--env") + 1] == "MYSQL_ROOT_PASSWORD"
            assert kwargs["env"]["MYSQL_ROOT_PASSWORD"] == owned.password
            assert (
                "/var/lib/mysql-files:rw,noexec,nosuid,nodev,mode=0700,uid=27,gid=27"
                in args
            )
            assert owned.containers == [args[args.index("--name") + 1]]
            if lost_ack:
                raise RuntimeError("uncertain Docker create acknowledgement")
        return "127.0.0.1:33060" if args[:2] == ["docker", "port"] else ""

    monkeypatch.setattr(fixture, "command", command)
    database = MagicMock()
    database.cursor.return_value.__enter__.return_value.fetchone.return_value = (
        "server-uuid",
        server_version,
        "MySQL Community Server - GPL",
    )
    monkeypatch.setattr(fixture, "connection", lambda config, credential: database)
    if lost_ack:
        with pytest.raises(RuntimeError, match="uncertain"):
            owned.start("valid")
    else:
        receipt = owned.start("valid")
        assert "password" not in receipt
        assert receipt["server_version"] == server_version
        database.close.assert_called_once()
    assert len([args for args, _ in calls if args[:2] == ["docker", "create"]]) == 1
    assert not list(tmp_path.glob("*.env"))


@pytest.mark.parametrize("server_version", ["8.4.11", "8.4.12"])
@pytest.mark.parametrize("failure", [None, "owner", "image", "stop"])
def test_close_preserves_diagnostics_volumes_and_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
    server_version: str,
) -> None:
    owned = fixture.Fixture(tmp_path, server_version)
    owned.tls.mkdir()
    for filename in ("ca-key.pem", "untrusted-ca-key.pem", "server-key.pem", "ca.pem"):
        (owned.tls / filename).write_text("disposable test marker")
    name = f"semantix-mysql-p5-{owned.identifier}-valid"
    owned.containers.append(name)
    owned.volumes.append(name + "-data")
    calls: list[list[str]] = []
    exists = True

    def command(args: list[str], **kwargs: object) -> str:
        nonlocal exists
        calls.append(args)
        if args[:3] == ["docker", "container", "ls"]:
            return name if exists else ""
        if args[:2] == ["docker", "inspect"]:
            return json.dumps(
                [
                    {
                        "Image": "image-id",
                        "Config": {
                            "Image": "foreign-image"
                            if failure == "image"
                            else fixture.IMAGES[server_version],
                            "Labels": {
                                "semantix.fixture": "foreign"
                                if failure == "owner"
                                else owned.identifier,
                                "semantix.owner": fixture.OWNER,
                            },
                            "Env": ["MYSQL_ROOT_PASSWORD=" + owned.password],
                        },
                        "HostConfig": {"PortBindings": {}},
                        "Mounts": [{"Type": "volume", "Name": name + "-data"}],
                    }
                ]
            )
        if args[:3] == ["docker", "image", "inspect"]:
            assert args[3] == fixture.IMAGES[server_version]
            return "image-id"
        if args[:2] == ["docker", "stop"] and failure == "stop":
            raise RuntimeError("stop failed")
        if args[:2] == ["docker", "logs"]:
            assert kwargs["include_stderr"]
            assert kwargs["credential"] == owned.password
            return "server stdout and stderr diagnostic " + owned.password
        if args[:2] == ["docker", "rm"]:
            assert args == ["docker", "rm", name]
            exists = False
        if args[:3] == ["docker", "volume", "inspect"]:
            return json.dumps(
                [
                    {
                        "Labels": {
                            "semantix.fixture": owned.identifier,
                            "semantix.owner": fixture.OWNER,
                        }
                    }
                ]
            )
        return ""

    monkeypatch.setattr(fixture, "command", command)
    if failure:
        with pytest.raises(RuntimeError):
            owned.close()
        assert all(
            (owned.tls / key).exists() for key in ("ca-key.pem", "server-key.pem")
        )
        assert ["docker", "rm", name] not in calls
        if failure != "stop":
            assert not any(args[:2] == ["docker", "stop"] for args in calls)
    else:
        owned.close()
        owned.close()
        assert (owned.tls / "ca.pem").read_text() == "disposable test marker"
        assert not list(owned.tls.glob("*-key.pem"))
        assert calls.index(["docker", "stop", "--timeout", "5", name]) < calls.index(
            ["docker", "rm", name]
        )
        snapshot = json.loads((tmp_path / (name + ".json")).read_text())
        assert "Env" not in snapshot
        assert owned.password not in json.dumps(snapshot)
        assert snapshot["volumes"] == owned.volumes
        logs = (tmp_path / (name + ".log")).read_text()
        assert "server stdout and stderr diagnostic" in logs
        assert owned.password not in logs
        assert not any(args[:3] == ["docker", "volume", "rm"] for args in calls)


def test_directory_marker_change_prevents_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = fixture.Fixture(tmp_path)
    (tmp_path / "fixture.json").write_text("{}")
    command = MagicMock()
    monkeypatch.setattr(fixture, "command", command)
    with pytest.raises(RuntimeError, match="directory ownership changed"):
        owned.close()
    command.assert_not_called()


@pytest.mark.parametrize("outcome", [0, 7, "timeout"])
def test_child_receipt_environment_and_persisted_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: int | str,
) -> None:
    owned = fixture.Fixture(tmp_path)
    monkeypatch.setattr(fixture, "private_directory", lambda: tmp_path)
    monkeypatch.setattr(fixture, "Fixture", lambda root, server_version: owned)
    monkeypatch.setattr(
        owned, "start", lambda kind: {"port": 33060, "server_version": "8.4.12"}
    )
    monkeypatch.setattr(sys, "argv", ["fixture", "--", "test-child"])

    def child(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        environment = kwargs["env"]
        receipt = json.loads(Path(environment["MYSQL_TEST_CONFIG"]).read_text())
        assert "password" not in receipt
        assert environment["MYSQL_TEST_PASSWORD"] == owned.password
        assert owned.password not in " ".join(args)
        stdout = ("child stdout " + owned.password).encode()
        stderr = ("child stderr " + owned.password).encode()
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(args, 1800, output=stdout, stderr=stderr)
        return subprocess.CompletedProcess(args, outcome, stdout, stderr)

    monkeypatch.setattr(fixture.subprocess, "run", child)
    if outcome == "timeout":
        with pytest.raises(RuntimeError, match="sanitized partial output"):
            fixture.main()
    else:
        assert fixture.main() == outcome
    for stream in ("stdout", "stderr"):
        text = (tmp_path / ("child." + stream + ".log")).read_text()
        assert owned.password not in text
        assert "child " + stream in text
        assert "[redacted fixture credential]" in text
    assert owned.password not in capsys.readouterr().out
    assert owned.password not in (tmp_path / "connection.json").read_text()


def test_partial_startup_and_cleanup_errors_both_remain_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = fixture.Fixture(tmp_path)
    monkeypatch.setattr(fixture, "private_directory", lambda: tmp_path)
    monkeypatch.setattr(fixture, "Fixture", lambda root, server_version: owned)
    monkeypatch.setattr(sys, "argv", ["fixture", "--", "test-child"])
    startup = RuntimeError("provisioning failed")
    cleanup = RuntimeError("cleanup failed")
    monkeypatch.setattr(owned, "start", MagicMock(side_effect=startup))
    monkeypatch.setattr(owned, "close", MagicMock(side_effect=cleanup))
    with pytest.raises(ExceptionGroup) as caught:
        fixture.main()
    assert caught.value.exceptions == (startup, cleanup)
    owned.close.assert_called_once()


def test_failed_certificate_preparation_still_disposes_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = fixture.Fixture(tmp_path)
    monkeypatch.setattr(fixture, "private_directory", lambda: tmp_path)
    monkeypatch.setattr(fixture, "Fixture", lambda root, server_version: owned)
    monkeypatch.setattr(sys, "argv", ["fixture", "--", "test-child"])

    def failed_certificates(root: Path) -> Path:
        (root / "tls").mkdir()
        (root / "tls" / "ca-key.pem").write_text("disposable test marker")
        raise RuntimeError("certificate generation failed")

    monkeypatch.setattr(fixture, "certificates", failed_certificates)
    with pytest.raises(RuntimeError, match="certificate generation failed"):
        fixture.main()
    assert not (owned.tls / "ca-key.pem").exists()
    assert (tmp_path / "fixture.json").exists()


@pytest.mark.parametrize("include_stderr", [False, True])
def test_command_preserves_requested_diagnostic_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, include_stderr: bool
) -> None:
    monkeypatch.setattr(
        fixture.subprocess,
        "run",
        MagicMock(
            return_value=subprocess.CompletedProcess(
                [], 0, "stdout diagnostic\n", "stderr diagnostic\n"
            )
        ),
    )
    result = fixture.command(
        ["docker", "logs"], cwd=tmp_path, include_stderr=include_stderr
    )
    assert "stdout diagnostic" in result
    assert ("stderr diagnostic" in result) == include_stderr


@pytest.mark.parametrize("timeout", [False, True])
@pytest.mark.parametrize("complete_key", [False, True])
def test_public_permission_failure_is_bounded_and_secret_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    timeout: bool,
    complete_key: bool,
) -> None:
    owned = fixture.Fixture(tmp_path)
    key = "-----BEGIN PRIVATE KEY-----\nprivate-key-canary\n"
    if complete_key:
        key += "-----END PRIVATE KEY-----\n"
    output = (
        "permission denied "
        + owned.password
        + " https://user:proxy-canary@private.invalid/token\n"
        + key
    )
    output += "x" * 6000

    def failed(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] == 90
        if timeout:
            raise subprocess.TimeoutExpired(
                args, 90, output=output.encode(), stderr=output.encode()
            )
        return subprocess.CompletedProcess(args, 1, output, output)

    monkeypatch.setattr(fixture.subprocess, "run", failed)
    with pytest.raises(RuntimeError, match="sanitized output"):
        fixture.command(
            ["docker", "start", "--attach", "owned"],
            cwd=tmp_path,
            credential=owned.password,
            phase="TLS permissions execution",
        )
    public = capsys.readouterr().err
    assert owned.password not in public
    assert "private-key-canary" not in public
    assert "proxy-canary" not in public
    assert "private.invalid" not in public
    assert "permission denied" in public
    event = json.loads(public.removeprefix("Fixture command: "))
    assert event["status"] == ("timeout" if timeout else "failed")
    assert event["timeout_seconds"] == 90
    assert event["elapsed_seconds"] >= 0
    assert len(event["stdout"]) <= 4107
    assert len(event["stderr"]) <= 4107
    assert "[redacted private key]" in event["stdout"]
    assert "[redacted endpoint]" in event["stderr"]


def test_non_public_command_does_not_export_raw_inspect_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        fixture.subprocess,
        "run",
        MagicMock(
            return_value=subprocess.CompletedProcess(
                [], 1, "unknown-environment-secret", "private-inspect-output"
            )
        ),
    )
    with pytest.raises(RuntimeError):
        fixture.command(["docker", "inspect", "owned"], cwd=tmp_path)
    public = capsys.readouterr().err
    assert "unknown-environment-secret" not in public
    assert "private-inspect-output" not in public
    event = json.loads(public.removeprefix("Fixture command: "))
    assert event["status"] == "failed"
    assert "stdout" not in event
    assert "stderr" not in event


def test_failure_is_visible_even_when_private_diagnostic_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        fixture.subprocess,
        "run",
        MagicMock(
            return_value=subprocess.CompletedProcess([], 1, "", "permission denied")
        ),
    )
    monkeypatch.setattr(
        fixture, "private_write", MagicMock(side_effect=OSError("write failed"))
    )
    with pytest.raises(OSError, match="write failed"):
        fixture.command(
            ["docker", "start"], cwd=tmp_path, phase="TLS permissions execution"
        )
    assert "permission denied" in capsys.readouterr().err


def test_public_phase_success_records_monotonic_elapsed_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    times = iter([100.0, 100.25])
    monkeypatch.setattr(fixture.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        fixture.subprocess,
        "run",
        MagicMock(
            return_value=subprocess.CompletedProcess([], 0, "owned-container-id", "")
        ),
    )
    assert (
        fixture.command(
            ["docker", "create"], cwd=tmp_path, phase="TLS permissions create"
        )
        == "owned-container-id"
    )
    event = json.loads(capsys.readouterr().err.removeprefix("Fixture command: "))
    assert event["status"] == "succeeded"
    assert event["elapsed_seconds"] == pytest.approx(0.25)
    assert "stdout" not in event


@pytest.mark.parametrize("failure", [None, "create", "start"])
def test_permission_creation_and_execution_are_separate_without_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    owned = fixture.Fixture(tmp_path)
    owned.tls.mkdir()
    monkeypatch.setattr(fixture, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(fixture, "certificates", lambda root: owned.tls)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def command(args: list[str], **kwargs: object) -> str:
        calls.append((args, kwargs))
        assert owned.containers == [f"semantix-mysql-p5-{owned.identifier}-permissions"]
        if args[1] == failure:
            raise RuntimeError("controlled command failure")
        return "owned-container-id"

    monkeypatch.setattr(fixture, "command", command)
    if failure:
        with pytest.raises(RuntimeError, match="controlled"):
            owned.prepare()
        assert not owned.prepared
    else:
        owned.prepare()
        assert owned.prepared
    create, create_options = calls[0]
    assert create[:3] == ["docker", "create", "--rm"]
    assert fixture.IMAGE in create
    assert f"semantix.owner={fixture.OWNER}" in create
    assert f"semantix.fixture={owned.identifier}" in create
    assert f"type=bind,source={owned.tls},target=/tls" in create
    assert (
        create_options["phase"]
        == "TLS permissions image acquisition/container creation"
    )
    assert len(calls) == (1 if failure == "create" else 2)
    if failure != "create":
        assert calls[1][0] == ["docker", "start", "--attach", owned.containers[0]]
        assert 0 < calls[1][1]["timeout"] <= 90
        assert (
            calls[1][1]["phase"]
            == "TLS permissions container startup/filesystem changes"
        )


def test_permission_shared_deadline_cannot_dispatch_start_after_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = fixture.Fixture(tmp_path)
    owned.tls.mkdir()
    monkeypatch.setattr(fixture, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(fixture, "certificates", lambda root: owned.tls)
    times = iter([100.0, 191.0])
    monkeypatch.setattr(fixture.time, "monotonic", lambda: next(times))
    command = MagicMock(return_value="owned-container-id")
    monkeypatch.setattr(fixture, "command", command)
    with pytest.raises(RuntimeError, match="90-second budget"):
        owned.prepare()
    command.assert_called_once()
    assert command.call_args.args[0][:2] == ["docker", "create"]
    assert not owned.prepared
    assert len(owned.containers) == 1


def test_timeout_accepts_windows_already_decoded_partial_streams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        fixture.subprocess,
        "run",
        MagicMock(
            side_effect=subprocess.TimeoutExpired(
                ["docker", "create"],
                90,
                output="Pulling fs layer",
                stderr="registry diagnostic",
            )
        ),
    )
    with pytest.raises(RuntimeError, match="sanitized output"):
        fixture.command(
            ["docker", "create"], cwd=tmp_path, phase="TLS permissions create"
        )
    event = json.loads(capsys.readouterr().err.removeprefix("Fixture command: "))
    assert event["status"] == "timeout"
    assert event["stdout"] == "Pulling fs layer"
    assert event["stderr"] == "registry diagnostic"


def test_bounded_permission_diagnostics_keep_final_error_after_pull_progress(
    tmp_path: Path,
) -> None:
    output = (
        "Pulling fs layer\n" + "progress " * 1000 + "\nregistry connection timed out"
    )
    public = fixture.public_command_output(output, None, tmp_path)
    assert public.startswith("Pulling fs layer")
    assert public.endswith("registry connection timed out")
    assert "[truncated]" in public
    assert len(public) <= 4107


@pytest.mark.parametrize("server_version", ["8.4.11", "8.4.12"])
@pytest.mark.parametrize("failure", [False, True])
def test_explicit_image_acquisition_precedes_fixture_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: bool, server_version: str
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["fixture", "--server-version", server_version, "--pull-image"]
    )
    monkeypatch.setattr(fixture, "private_directory", lambda: tmp_path)
    initialize = MagicMock(side_effect=AssertionError("must not construct SQL fixture"))
    monkeypatch.setattr(fixture, "Fixture", initialize)
    generate = MagicMock(side_effect=AssertionError("must not generate TLS keys"))
    monkeypatch.setattr(fixture, "certificates", generate)
    command = MagicMock(
        side_effect=RuntimeError("image acquisition timed out") if failure else None
    )
    monkeypatch.setattr(fixture, "command", command)
    if failure:
        with pytest.raises(RuntimeError, match="image acquisition"):
            fixture.main()
    else:
        assert fixture.main() == 0
    command.assert_called_once_with(
        ["docker", "pull", fixture.IMAGES[server_version]],
        cwd=tmp_path,
        phase="Pinned MySQL image acquisition (attempt 1/2)",
        timeout=150,
    )
    initialize.assert_not_called()
    generate.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_image_acquisition_rejects_a_combined_test_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["fixture", "--pull-image", "--", "test-child"])
    command = MagicMock()
    monkeypatch.setattr(fixture, "command", command)
    with pytest.raises(SystemExit) as caught:
        fixture.main()
    assert caught.value.code == 2
    command.assert_not_called()


@pytest.mark.parametrize(
    "identity",
    [
        ("server-uuid", "8.4.11", "MySQL Community Server - GPL"),
        ("server-uuid", "8.4.12", "foreign server"),
        ("", "8.4.12", "MySQL Community Server - GPL"),
    ],
)
def test_server_identity_mismatch_fails_without_readiness_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, identity: tuple[str, str, str]
) -> None:
    owned = fixture.Fixture(tmp_path)
    owned.prepared = True
    monkeypatch.setattr(fixture, "command", MagicMock(return_value="127.0.0.1:33060"))
    database = MagicMock()
    database.cursor.return_value.__enter__.return_value.fetchone.return_value = identity
    connect = MagicMock(return_value=database)
    monkeypatch.setattr(fixture, "connection", connect)
    with pytest.raises(RuntimeError, match="identity/version mismatch"):
        owned.start("valid")
    connect.assert_called_once()
    database.close.assert_called_once()


def test_unverified_server_argument_rejected_before_fixture_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["fixture", "--server-version", "8.4.13", "--", "child"]
    )
    allocate = MagicMock(
        side_effect=AssertionError("Must not allocate private resources")
    )
    monkeypatch.setattr(fixture, "private_directory", allocate)
    with pytest.raises(SystemExit) as caught:
        fixture.main()
    assert caught.value.code == 2
    allocate.assert_not_called()


class PullClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.delays: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.now += delay


def pull_test_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> PullClock:
    clock = PullClock()
    monkeypatch.setattr(fixture.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(fixture.time, "sleep", clock.sleep)
    monkeypatch.setattr(fixture, "private_directory", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["fixture", "--pull-image"])
    monkeypatch.setattr(
        fixture,
        "Fixture",
        MagicMock(side_effect=AssertionError("must not construct SQL fixture")),
    )
    monkeypatch.setattr(
        fixture,
        "certificates",
        MagicMock(side_effect=AssertionError("must not create TLS keys")),
    )
    return clock


@pytest.mark.parametrize("first", ["success", "timeout", "transport"])
def test_pull_success_and_transient_retry_are_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    first: str,
) -> None:
    clock = pull_test_setup(tmp_path, monkeypatch)
    timeouts: list[float] = []

    def run(args: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        assert args == ["docker", "pull", fixture.IMAGE]
        assert options["capture_output"]
        assert options["text"]
        assert not options["check"]
        timeouts.append(options["timeout"])
        if len(timeouts) == 1 and first == "timeout":
            clock.now += options["timeout"]
            raise subprocess.TimeoutExpired(
                args,
                options["timeout"],
                output=b"Verifying Checksum\nPull complete",
                stderr=b"",
            )
        if len(timeouts) == 1 and first == "transport":
            clock.now += 1
            return subprocess.CompletedProcess(args, 1, "", "connection reset by peer")
        clock.now += 2
        return subprocess.CompletedProcess(args, 0, "verified pinned image", "")

    monkeypatch.setattr(fixture.subprocess, "run", run)
    assert fixture.main() == 0
    assert timeouts == (
        [150] if first == "success" else [150, 85] if first == "timeout" else [150, 150]
    )
    assert clock.delays == ([] if first == "success" else [5])
    fixture.Fixture.assert_not_called()
    fixture.certificates.assert_not_called()
    assert not (tmp_path / "tls").exists()
    output = capsys.readouterr().err
    assert output.count('"status": "succeeded"') == 1
    assert output.count('"status": "timeout"') == (first == "timeout")
    assert output.count('"category": "transport"') == (first == "transport")


def test_pull_timeout_exhaustion_caps_attempts_and_total_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clock = pull_test_setup(tmp_path, monkeypatch)
    timeouts: list[float] = []

    def run(args: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        timeouts.append(options["timeout"])
        clock.now += options["timeout"]
        raise subprocess.TimeoutExpired(args, options["timeout"])

    monkeypatch.setattr(fixture.subprocess, "run", run)
    with pytest.raises(fixture.ImageAcquisitionError) as caught:
        fixture.main()
    assert caught.value.category == "timeout"
    assert timeouts == [150, 85]
    assert clock.delays == [5]
    assert clock.now == 340
    fixture.Fixture.assert_not_called()
    fixture.certificates.assert_not_called()
    events = [
        json.loads(line.removeprefix("Fixture command: "))
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("Fixture command: ")
    ]
    assert len(events) == 2
    assert [e["elapsed_seconds"] for e in events] == [150, 85]
    assert all(e["category"] == "timeout" for e in events)
    assert len((tmp_path / "command-failures.jsonl").read_text().splitlines()) == 2


@pytest.mark.parametrize(
    "diagnostic",
    [
        "unauthorized: authentication required; connection reset by peer",
        "manifest unknown",
        "no matching manifest for linux",
        "invalid reference format",
        "digest mismatch; connection reset",
        "checksum verification failed",
        "x509: certificate signed by unknown authority",
        "permission denied",
        "no space left on device",
        "Cannot connect to the Docker daemon",
        "unrecognized registry failure",
    ],
)
def test_permanent_and_unknown_pull_failures_are_not_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    diagnostic: str,
) -> None:
    clock = pull_test_setup(tmp_path, monkeypatch)
    run = MagicMock(return_value=subprocess.CompletedProcess([], 1, "", diagnostic))
    monkeypatch.setattr(fixture.subprocess, "run", run)
    with pytest.raises(fixture.ImageAcquisitionError):
        fixture.main()
    run.assert_called_once()
    assert not clock.delays
    fixture.Fixture.assert_not_called()
    fixture.certificates.assert_not_called()


def test_pull_backoff_cannot_start_an_expired_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = pull_test_setup(tmp_path, monkeypatch)

    def run(args: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        clock.now += 150
        raise subprocess.TimeoutExpired(args, options["timeout"])

    run_mock = MagicMock(side_effect=run)
    monkeypatch.setattr(fixture.subprocess, "run", run_mock)

    def oversleep(delay: float) -> None:
        clock.delays.append(delay)
        clock.now += 90

    monkeypatch.setattr(fixture.time, "sleep", oversleep)
    with pytest.raises(RuntimeError, match="240-second budget"):
        fixture.main()
    run_mock.assert_called_once()
    assert clock.delays == [5]


@pytest.mark.parametrize("interrupted", [KeyboardInterrupt, FileNotFoundError])
def test_pull_interruption_or_local_failure_does_not_retry_or_initialize(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    interrupted: type[BaseException],
) -> None:
    clock = pull_test_setup(tmp_path, monkeypatch)
    run = MagicMock(side_effect=interrupted("private path canary"))
    monkeypatch.setattr(fixture.subprocess, "run", run)
    with pytest.raises(
        KeyboardInterrupt if interrupted is KeyboardInterrupt else RuntimeError
    ):
        fixture.main()
    run.assert_called_once()
    assert not clock.delays
    fixture.Fixture.assert_not_called()
    fixture.certificates.assert_not_called()
    assert "private path canary" not in capsys.readouterr().err


def test_pull_diagnostics_redact_paths_credentials_endpoints_and_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pull_test_setup(tmp_path, monkeypatch)
    output = (
        str(tmp_path)
        + " https://user:credential-canary@private.invalid/token "
        + ("-----BEGIN PRIVATE KEY-----\nkey-canary\n-----END PRIVATE KEY-----")
    )
    monkeypatch.setattr(
        fixture.subprocess,
        "run",
        MagicMock(
            return_value=subprocess.CompletedProcess([], 1, output, "unauthorized")
        ),
    )
    with pytest.raises(fixture.ImageAcquisitionError):
        fixture.main()
    public = capsys.readouterr().err
    assert str(tmp_path) not in public
    assert "credential-canary" not in public
    assert "private.invalid" not in public
    assert "key-canary" not in public
    assert '"category": "permanent"' in public


def test_image_acquisition_never_replays_a_failed_integration_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned = fixture.Fixture(tmp_path)
    monkeypatch.setattr(fixture, "private_directory", lambda: tmp_path)
    monkeypatch.setattr(fixture, "Fixture", MagicMock(return_value=owned))
    start = MagicMock(return_value={"port": 33060, "server_version": "8.4.12"})
    monkeypatch.setattr(owned, "start", start)
    child = MagicMock(return_value=subprocess.CompletedProcess(["tests"], 7, b"", b""))
    monkeypatch.setattr(fixture.subprocess, "run", child)
    pull = MagicMock(side_effect=AssertionError("must not acquire/retry during tests"))
    monkeypatch.setattr(fixture, "pull_image", pull)
    monkeypatch.setattr(sys, "argv", ["fixture", "--", "tests"])
    assert fixture.main() == 7
    child.assert_called_once()
    fixture.Fixture.assert_called_once()
    assert start.call_count == 3
    pull.assert_not_called()


def test_repeated_transport_failure_stops_at_two_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = pull_test_setup(tmp_path, monkeypatch)
    run = MagicMock(
        return_value=subprocess.CompletedProcess([], 1, "", "503 Service Unavailable")
    )
    monkeypatch.setattr(fixture.subprocess, "run", run)
    with pytest.raises(fixture.ImageAcquisitionError) as caught:
        fixture.main()
    assert caught.value.category == "transport"
    assert run.call_count == 2
    assert clock.delays == [5]
    fixture.Fixture.assert_not_called()


@pytest.mark.parametrize("write_cost", [80, 85])
def test_pull_private_diagnostic_cost_reduces_remaining_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_cost: int,
) -> None:
    clock = pull_test_setup(tmp_path, monkeypatch)
    timeouts: list[float] = []

    def run(args: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        timeouts.append(options["timeout"])
        if len(timeouts) == 1:
            clock.now += 150
            raise subprocess.TimeoutExpired(args, options["timeout"])
        clock.now += 1
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(fixture.subprocess, "run", run)
    write = fixture.private_write

    def delayed_write(path: Path, data: bytes, *, append: bool = False) -> None:
        write(path, data, append=append)
        clock.now += write_cost

    monkeypatch.setattr(fixture, "private_write", delayed_write)
    if write_cost == 80:
        assert fixture.main() == 0
        assert timeouts == [150, 5]
        assert clock.delays == [5]
    else:
        with pytest.raises(RuntimeError, match="240-second budget"):
            fixture.main()
        assert timeouts == [150]
        assert not clock.delays
    fixture.Fixture.assert_not_called()


def test_pull_late_success_does_not_bypass_total_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = pull_test_setup(tmp_path, monkeypatch)

    def run(args: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        clock.now += 241
        return subprocess.CompletedProcess(args, 0, "", "")

    run_mock = MagicMock(side_effect=run)
    monkeypatch.setattr(fixture.subprocess, "run", run_mock)
    with pytest.raises(RuntimeError, match="240-second budget"):
        fixture.main()
    run_mock.assert_called_once()
    fixture.Fixture.assert_not_called()
    assert not clock.delays


def test_permanent_pull_diagnostic_takes_precedence_over_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = pull_test_setup(tmp_path, monkeypatch)
    run = MagicMock(
        side_effect=subprocess.TimeoutExpired(
            ["docker", "pull", fixture.IMAGE], 150, stderr=b"unauthorized; i/o timeout"
        )
    )
    monkeypatch.setattr(fixture.subprocess, "run", run)
    with pytest.raises(fixture.ImageAcquisitionError) as caught:
        fixture.main()
    assert caught.value.category == "permanent"
    run.assert_called_once()
    assert not clock.delays


def test_pull_interrupt_kills_cli_and_exits_its_process_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = pull_test_setup(tmp_path, monkeypatch)
    process = MagicMock()
    process.__enter__.return_value = process
    process.communicate.side_effect = KeyboardInterrupt()
    lifecycle: list[str] = []
    process.kill.side_effect = lambda: lifecycle.append("kill")

    def exited(*args: object) -> bool:
        lifecycle.append("exit")
        return False

    process.__exit__.side_effect = exited
    create = MagicMock(return_value=process)
    monkeypatch.setattr(fixture.subprocess, "Popen", create)
    with pytest.raises(KeyboardInterrupt):
        fixture.main()
    create.assert_called_once()
    assert lifecycle == ["kill", "exit"]
    assert not clock.delays
    fixture.Fixture.assert_not_called()


@pytest.mark.parametrize("code", [-2, -15, 130, 137, 143, 0xC000013A])
def test_interrupted_pull_exit_is_terminal_despite_partial_transport_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: int,
) -> None:
    clock = pull_test_setup(tmp_path, monkeypatch)
    run = MagicMock(
        return_value=subprocess.CompletedProcess(
            [], code, "", "connection reset by peer"
        )
    )
    monkeypatch.setattr(fixture.subprocess, "run", run)
    with pytest.raises(fixture.ImageAcquisitionError) as caught:
        fixture.main()
    assert caught.value.category == "interrupted"
    run.assert_called_once()
    assert not clock.delays
    fixture.Fixture.assert_not_called()
