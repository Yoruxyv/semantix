"""Credential handoff, private files and owned disposal without a Docker daemon."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
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


@pytest.mark.parametrize("lost_ack", [False, True])
def test_start_uses_environment_and_tracks_uncertain_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lost_ack: bool
) -> None:
    owned = fixture.Fixture(tmp_path)
    owned.prepared = True
    calls: list[tuple[list[str], dict[str, object]]] = []

    def command(args: list[str], **kwargs: object) -> str:
        calls.append((args, kwargs))
        assert owned.password not in " ".join(args)
        assert "--env-file" not in args
        if args[:2] == ["docker", "create"]:
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
        "8.4.12",
    )
    monkeypatch.setattr(fixture, "connection", lambda config, credential: database)
    if lost_ack:
        with pytest.raises(RuntimeError, match="uncertain"):
            owned.start("valid")
    else:
        receipt = owned.start("valid")
        assert "password" not in receipt
        assert receipt["server_version"] == "8.4.12"
        database.close.assert_called_once()
    assert len([args for args, _ in calls if args[:2] == ["docker", "create"]]) == 1
    assert not list(tmp_path.glob("*.env"))


@pytest.mark.parametrize("failure", [None, "owner", "image", "stop"])
def test_close_preserves_diagnostics_volumes_and_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    owned = fixture.Fixture(tmp_path)
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
                            else fixture.IMAGE,
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
    monkeypatch.setattr(fixture, "Fixture", lambda root: owned)
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
    monkeypatch.setattr(fixture, "Fixture", lambda root: owned)
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
    monkeypatch.setattr(fixture, "Fixture", lambda root: owned)
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
