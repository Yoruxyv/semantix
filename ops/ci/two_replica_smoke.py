"""Exercise the disposable production Compose stack through its real gateway."""

import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

COMPOSE = ("docker", "compose", "-f", "docker-compose.prod.yml")
BASE = f"http://127.0.0.1:{os.environ.get('SEMANTIX_PORT', '18080')}"
TOKENS = {
    "admin": os.environ["SEMANTIX_E2E_TOKEN"],
    "viewer": os.environ["SEMANTIX_E2E_VIEWER_TOKEN"],
    "operator": os.environ["SEMANTIX_E2E_OPERATOR_TOKEN"],
    "scoped_admin": os.environ["SEMANTIX_E2E_SCOPED_ADMIN_TOKEN"],
}
UPSTREAM_FILE = Path(os.environ["SEMANTIX_UPSTREAM_FILE"])
UPSTREAM_ORIGINAL = UPSTREAM_FILE.read_text(encoding="utf-8")
QUERY_PATH = "/api/v1/query"


def run(*command: str) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise AssertionError(f"Command failed: {result.stderr[-1200:]}")
    return result.stdout


def compose(*arguments: str) -> str:
    return run(*COMPOSE, *arguments)


def request(
    path: str,
    *,
    role: str = "admin",
    method: str = "GET",
    payload: dict[str, object] | None = None,
    backend: str | None = None,
    expected: int = 200,
    timeout_seconds: int = 20,
) -> dict[str, object]:
    url = f"http://{backend}:8000{path}" if backend else f"{BASE}{path}"
    command = [
        "curl",
        "--silent",
        "--show-error",
        "--max-time",
        str(timeout_seconds),
        "--write-out",
        "\n%{http_code}",
        "--request",
        method,
        "--header",
        f"Authorization: Bearer {TOKENS.get(role, role)}",
    ]
    if payload is not None:
        command += [
            "--header",
            "Content-Type: application/json",
            "--data",
            json.dumps(payload),
        ]
    command.append(url)
    if backend:
        command = [*COMPOSE, "exec", "-T", "frontend", *command]
    body, status_text = run(*command).rsplit("\n", 1)
    status = int(status_text)
    if status != expected:
        raise AssertionError(
            f"{method} {path} via {backend or 'gateway'}: {status}, {body[:300]}"
        )
    return json.loads(body) if body else {}


def query(
    prompt: str,
    *,
    backend: str | None = None,
    namespace: str = "alpha",
    **policy: object,
) -> dict[str, object]:
    return request(
        QUERY_PATH,
        role="operator" if namespace == "alpha" else "admin",
        method="POST",
        payload={"prompt": prompt, "namespace": namespace, **policy},
        backend=backend,
    )


def edge_ip(service: str) -> str:
    container = compose("ps", "-q", service).strip()
    networks = json.loads(
        run(
            "docker",
            "inspect",
            "--format",
            "{{json .NetworkSettings.Networks}}",
            container,
        )
    )
    return next(
        value["IPAddress"] for name, value in networks.items() if name.endswith("_edge")
    )


def gateway_upstreams(path: str) -> list[str]:
    logs = compose("logs", "--no-color", "frontend")
    return re.findall(
        rf"upstream=([0-9.]+):8000 .*?path={re.escape(path)}(?:\s|$)", logs
    )


def wait_gateway_upstream(ip: str) -> None:
    path = "/api/v1/cache/threshold"
    for _ in range(20):
        before = len(gateway_upstreams(path))
        for _ in range(3):
            request(path)
        if gateway_upstreams(path)[before:] == [ip] * 3:
            return
        time.sleep(0.1)
    raise AssertionError(f"Gateway did not settle on upstream {ip}")


def backend_logs(service: str, *, since: str | None = None) -> str:
    args = ["logs", "--no-color", "--timestamps"]
    if since:
        args += ["--since", since]
    return compose(*args, service)


def set_upstream(service: str | None) -> None:
    if service is None:
        UPSTREAM_FILE.write_text(UPSTREAM_ORIGINAL, encoding="utf-8")
    else:
        UPSTREAM_FILE.write_text(
            "resolver 127.0.0.11 valid=5s ipv6=off;\n"
            "upstream semantix_backend {\n"
            "    zone semantix_backend 64k;\n"
            f"    server {service}:8000 resolve max_fails=2 fail_timeout=5s;\n"
            "}\n",
            encoding="utf-8",
        )
    compose("exec", "-T", "frontend", "nginx", "-t")
    compose("exec", "-T", "frontend", "nginx", "-s", "reload")


def wait_healthy(service: str) -> None:
    container = compose("ps", "-q", service).strip()
    for _ in range(90):
        status = run(
            "docker", "inspect", "--format", "{{.State.Health.Status}}", container
        ).strip()
        if status == "healthy":
            return
        time.sleep(1)
    raise AssertionError(f"{service} did not become healthy")


def db_connections() -> int:
    role = os.environ["POSTGRES_RUNTIME_USER"]
    database = os.environ["POSTGRES_DB"]
    sql = f"SELECT count(*) FROM pg_stat_activity WHERE usename = '{role}' AND datname = '{database}'"
    return int(
        compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            os.environ["POSTGRES_MIGRATION_USER"],
            "-d",
            database,
            "-Atc",
            sql,
        ).strip()
    )


def provider_peak(since: str) -> tuple[int, int]:
    events = []
    counts = {}
    for service in ("backend-a", "backend-b"):
        log = backend_logs(service, since=since)
        starts = log.count("Mock generation started")
        counts[service] = starts
        for line in log.splitlines():
            if (
                "Mock generation started" not in line
                and "Mock generation finished" not in line
            ):
                continue
            match = re.search(
                r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)", line
            )
            assert match, line
            timestamp = match.group()
            direction = 1 if "Mock generation started" in line else -1
            events.append(
                (datetime.fromisoformat(timestamp.replace("Z", "+00:00")), direction)
            )
    active = peak = 0
    for _, direction in sorted(events, key=lambda event: (event[0], event[1])):
        active += direction
        peak = max(peak, active)
    assert active == 0, "Mock provider calls did not finish"
    return peak, sum(counts.values())


def verify_cache() -> None:
    prompt = f"shared-cache-{uuid4().hex}"
    assert query(prompt, backend="backend-a")["provider_called"] is True
    assert query(prompt, backend="backend-b")["cache_hit"] is True
    assert query(prompt, backend="backend-b", namespace="beta")["cache_hit"] is False
    hit = query(prompt, backend="backend-a")
    assert hit["cache_hit"] is True
    request(
        f"/api/v1/cache/entries/{hit['matched_cache_key']}",
        method="DELETE",
        backend="backend-b",
    )
    assert query(prompt, backend="backend-a")["cache_hit"] is False
    request("/api/v1/cache?namespace=alpha", method="DELETE", backend="backend-b")
    assert query(prompt, backend="backend-a")["cache_hit"] is False
    assert query(prompt, backend="backend-a", namespace="beta")["cache_hit"] is True

    expiring = f"ttl-{uuid4().hex}"
    assert (
        query(expiring, backend="backend-a", cache_ttl_seconds=1)["cache_hit"] is False
    )
    assert query(expiring, backend="backend-b")["cache_hit"] is True
    time.sleep(1.2)
    assert query(expiring, backend="backend-b")["cache_hit"] is False


def verify_auth_and_limits() -> None:
    request("/api/v1/cache/stats?namespace=alpha", role="viewer", backend="backend-a")
    request(
        QUERY_PATH,
        role="viewer",
        method="POST",
        payload={"prompt": "denied", "namespace": "alpha"},
        backend="backend-b",
        expected=403,
    )
    request(
        QUERY_PATH,
        role="operator",
        method="POST",
        payload={"prompt": "denied", "namespace": "beta"},
        backend="backend-a",
        expected=403,
    )
    request(
        "/api/v1/cache?namespace=alpha",
        role="operator",
        method="DELETE",
        backend="backend-b",
        expected=403,
    )
    request(
        "/api/v1/cache/threshold",
        role="scoped_admin",
        method="PUT",
        payload={"threshold": 0.8},
        backend="backend-a",
        expected=403,
    )
    request(
        "/api/v1/cache/threshold",
        method="PUT",
        payload={"threshold": 0.8},
        backend="backend-b",
    )
    assert request("/api/v1/cache/threshold", backend="backend-a")["threshold"] == 0.8
    request(
        "/api/v1/cache/threshold",
        method="PUT",
        payload={"threshold": 0.92},
        backend="backend-a",
    )
    request("/api/v1/cache/entries?namespace=alpha", role="invalid-token", expected=401)

    for index, expected in enumerate((401, 401, 429)):
        request(
            "/api/v1/auth/session",
            role="invalid-token",
            backend=("backend-a", "backend-b")[index % 2],
            expected=expected,
        )
    request("/api/v1/auth/session", backend="backend-b", expected=429)

    quota = int(os.environ["RATE_LIMIT"].split("/", 1)[0])
    for index in range(quota):
        request(
            "/api/v1/cache/entries?namespace=alpha",
            backend=("backend-a", "backend-b")[index % 2],
        )
    request("/api/v1/cache/entries?namespace=alpha", backend="backend-a", expected=429)


def verify_failover() -> int:
    failures: list[str] = []

    def traffic() -> None:
        while not stopped[0]:
            try:
                request("/health")
            except (AssertionError, subprocess.SubprocessError) as error:
                failures.append(str(error))
            time.sleep(0.05)

    stopped = [False]
    with ThreadPoolExecutor(max_workers=1) as executor:
        worker = executor.submit(traffic)
        try:
            for service in ("backend-a", "backend-b"):
                compose("stop", service)
                request("/ready")
                request(
                    QUERY_PATH,
                    method="POST",
                    payload={"prompt": f"failover-{service}", "cache_enabled": False},
                )
                compose("start", service)
                wait_healthy(service)
        finally:
            stopped[0] = True
            worker.result(timeout=10)
    assert not failures, f"Transient gateway failures: {failures[:3]}"
    return len(failures)


def verify_drain(ip_a: str, ip_b: str) -> None:
    set_upstream("backend-a")
    wait_gateway_upstream(ip_a)
    started_before = backend_logs("backend-a").count("Mock generation started")
    with ThreadPoolExecutor(max_workers=1) as executor:
        active = executor.submit(
            request,
            QUERY_PATH,
            method="POST",
            payload={"prompt": f"drain-{uuid4().hex}", "cache_enabled": False},
        )
        for _ in range(50):
            if (
                backend_logs("backend-a").count("Mock generation started")
                > started_before
            ):
                break
            time.sleep(0.1)
        else:
            raise AssertionError("Active request did not reach backend A")
        set_upstream("backend-b")
        wait_gateway_upstream(ip_b)
        before = len(gateway_upstreams("/api/v1/cache/threshold"))
        for _ in range(6):
            request("/api/v1/cache/threshold")
        assert gateway_upstreams("/api/v1/cache/threshold")[before:] == [ip_b] * 6
        assert active.result(timeout=20)["provider_called"] is True
    compose("stop", "backend-a")
    container = compose("ps", "-a", "-q", "backend-a").strip()
    assert (
        run("docker", "inspect", "--format", "{{.State.ExitCode}}", container).strip()
        == "0"
    )
    assert "Application shutdown complete" in backend_logs("backend-a")
    assert 1 <= db_connections() <= int(os.environ.get("DATABASE_POOL_MAX_SIZE", "5"))
    request("/ready")
    compose("start", "backend-a")
    wait_healthy("backend-a")
    set_upstream(None)


def verify_blocked_db_shutdown(ip_a: str, ip_b: str) -> float:
    seed = f"blocked-db-seed-{uuid4().hex}"
    assert query(seed, backend="backend-a", cache_read_enabled=False)["provider_called"]
    set_upstream("backend-a")
    wait_gateway_upstream(ip_a)
    locker = subprocess.Popen(
        [
            *COMPOSE,
            "exec",
            "-T",
            "-e",
            "PGAPPNAME=semantix-blocked-db-smoke",
            "postgres",
            "psql",
            "-X",
            "-q",
            "-U",
            os.environ["POSTGRES_MIGRATION_USER"],
            "-d",
            os.environ["POSTGRES_DB"],
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    def count(sql: str) -> int:
        return int(
            compose(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                os.environ["POSTGRES_MIGRATION_USER"],
                "-d",
                os.environ["POSTGRES_DB"],
                "-Atc",
                sql,
            ).strip()
        )

    def wait_for(sql: str, description: str) -> None:
        for _ in range(60):
            if count(sql):
                return
            assert locker.poll() is None, f"Lock session exited before {description}"
            time.sleep(0.1)
        raise AssertionError(f"Timed out waiting for {description}")

    try:
        assert locker.stdin is not None
        locker.stdin.write(
            "SELECT pg_advisory_lock(hashtext((SELECT embedding_space "
            "FROM semantix.cache_entries LIMIT 1)));\n"
        )
        locker.stdin.flush()
        wait_for(
            "SELECT count(*) FROM pg_stat_activity a JOIN pg_locks l USING (pid) "
            "WHERE a.application_name = 'semantix-blocked-db-smoke' "
            "AND l.locktype = 'advisory' AND l.granted",
            "held advisory lock",
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            active = executor.submit(
                request,
                QUERY_PATH,
                method="POST",
                payload={
                    "prompt": f"blocked-db-{uuid4().hex}",
                    "namespace": "alpha",
                    "cache_read_enabled": False,
                },
                timeout_seconds=60,
            )
            wait_for(
                "SELECT count(*) FROM pg_stat_activity WHERE "
                "usename = 'semantix_runtime' AND wait_event_type = 'Lock' "
                "AND query LIKE 'SELECT pg_advisory_xact_lock%'",
                "blocked backend database operation",
            )
            set_upstream("backend-b")
            wait_gateway_upstream(ip_b)
            stop_started = time.monotonic()
            stopped = executor.submit(compose, "stop", "backend-a")
            request("/ready")
            query(f"surviving-peer-{uuid4().hex}", cache_enabled=False)
            assert not active.done() and not stopped.done(), (
                "The blocked request or replica stop finished before DB release"
            )
            locker.stdin.write("SELECT pg_advisory_unlock_all();\n\\q\n")
            locker.stdin.flush()
            assert locker.wait(timeout=10) == 0
            assert active.result(timeout=45)["provider_called"] is True
            stopped.result(timeout=45)
            shutdown_seconds = time.monotonic() - stop_started

        container = compose("ps", "-a", "-q", "backend-a").strip()
        assert (
            run(
                "docker", "inspect", "--format", "{{.State.ExitCode}}", container
            ).strip()
            == "0"
        )
        assert "Application shutdown complete" in backend_logs("backend-a")
        assert (
            1 <= db_connections() <= int(os.environ.get("DATABASE_POOL_MAX_SIZE", "5"))
        )
        request("/ready")
        assert query(seed, backend="backend-b")["cache_hit"] is True
        compose("start", "backend-a")
        wait_healthy("backend-a")
        request("/ready", backend="backend-a")
        return shutdown_seconds
    finally:
        if locker.poll() is None:
            assert locker.stdin is not None
            locker.stdin.write("SELECT pg_advisory_unlock_all();\n\\q\n")
            locker.stdin.flush()
            locker.wait(timeout=10)
        compose("start", "backend-a")
        wait_healthy("backend-a")
        set_upstream(None)


def main() -> None:
    ip_a, ip_b = edge_ip("backend-a"), edge_ip("backend-b")
    assert ip_a != ip_b
    idle_connections = db_connections()
    assert 2 <= idle_connections <= 10
    try:
        before = len(gateway_upstreams(QUERY_PATH))
        for index in range(12):
            query(f"distribution-{uuid4().hex}-{index}", cache_enabled=False)
        served = gateway_upstreams(QUERY_PATH)[before:]
        assert {ip_a, ip_b}.issubset(served), (
            f"Only these upstreams served traffic: {set(served)}"
        )

        verify_cache()
        transient_errors = verify_failover()
        verify_drain(ip_a, ip_b)
        blocked_db_shutdown_seconds = verify_blocked_db_shutdown(ip_a, ip_b)

        since = datetime.now(UTC).isoformat()
        with ThreadPoolExecutor(max_workers=12) as executor:
            burst = [
                executor.submit(
                    query, f"cold-burst-{uuid4().hex}-{index}", cache_enabled=False
                )
                for index in range(12)
            ]
            observed_connections = [db_connections()]
            responses = [work.result(timeout=20) for work in burst]
        assert all(response["provider_called"] for response in responses)
        peak, calls = provider_peak(since)
        assert calls == 12 and 2 <= peak <= 12, (calls, peak)
        assert max(observed_connections) <= 10

        coalesce_since = datetime.now(UTC).isoformat()
        shared_prompt = f"coalesced-{uuid4().hex}"
        with ThreadPoolExecutor(max_workers=12) as executor:
            same_prompt = [executor.submit(query, shared_prompt) for _ in range(12)]
            coalesced_responses = [work.result(timeout=20) for work in same_prompt]
        _, coalesced_calls = provider_peak(coalesce_since)
        assert 1 <= coalesced_calls <= 2, coalesced_calls
        assert (
            sum(bool(response["provider_called"]) for response in coalesced_responses)
            == coalesced_calls
        )

        verify_auth_and_limits()
        print(
            f"two-replica verification: upstreams=2 idle_db={idle_connections} observed_db_peak={max(observed_connections)} mock_provider_peak={peak} cold_generation_calls={calls} same_prompt_generation_calls={coalesced_calls} transient_errors={transient_errors} blocked_db_shutdown_s={blocked_db_shutdown_seconds:.2f}"
        )
    finally:
        set_upstream(None)


if __name__ == "__main__":
    main()
