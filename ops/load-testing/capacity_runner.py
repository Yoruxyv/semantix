"""Run isolated one- and two-replica k6 capacity measurements."""

import argparse
import hashlib
import json
import os
import platform
import re
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).parent
PROFILES = ("cache-heavy", "generation-heavy", "mixed-policy")
LADDER = (50, 100, 250, 500, 1000)
RATE_LIMIT = "100000/minute"
MOCK_DELAY = "0.05"
PORT = "18081"
K6_IMAGE = (
    "grafana/k6@sha256:e7eeddf1ce2361df6920d925297f487c0ba549c44be242c6a9c22f28d9b08efa"
)


def command(*args: str, env: Mapping[str, str] | None) -> str:
    result = subprocess.run(
        args, cwd=ROOT, env=env, capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise RuntimeError(f"{' '.join(args[:4])}: {result.stderr[-1500:]}")
    return result.stdout


def compose(env: dict[str, str], *args: str) -> str:
    return command("docker", "compose", "-f", "docker-compose.prod.yml", *args, env=env)


def api(
    env: dict[str, str],
    path: str,
    *,
    token: str = "",
    method: str = "GET",
    payload: dict | None = None,
) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def direct(
    env: dict[str, str],
    service: str,
    path: str,
    token: str = "",
    *,
    method: str = "GET",
    payload: dict | None = None,
) -> tuple[int, dict, float]:
    started = time.monotonic()
    args = [
        "exec",
        "-T",
        "frontend",
        "curl",
        "-sS",
        "--max-time",
        "5",
        "-w",
        "\n%{http_code}",
    ]
    if token:
        args += ["-H", f"Authorization: Bearer {token}"]
    if method != "GET":
        args += ["--request", method]
    if payload is not None:
        args += ["-H", "Content-Type: application/json", "--data", json.dumps(payload)]
    args += [f"http://{service}:8000{path}"]
    output = compose(env, *args)
    body, status = output.rsplit("\n", 1)
    return int(status), json.loads(body), (time.monotonic() - started) * 1000


def snapshot(env: dict[str, str], services: list[str], admin: str) -> dict:
    sample: dict = {"at": datetime.now(UTC).isoformat(), "replicas": {}}
    for service in services:
        status, _, latency = direct(env, service, "/ready")
        health_status, _, health_latency = direct(env, service, "/health")
        metrics_status, metrics, _ = direct(env, service, "/api/v1/metrics", admin)
        container = compose(env, "ps", "-q", service).strip()
        inspection = json.loads(
            command("docker", "inspect", "--format", "{{json .}}", container, env=env)
        )
        stats = json.loads(
            command(
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{json .}}",
                container,
                env=env,
            )
        )
        sample["replicas"][service] = {
            "ready_status": status,
            "ready_ms": round(latency, 1),
            "health_status": health_status,
            "health_ms": round(health_latency, 1),
            "healthcheck": inspection["State"]["Health"]["Status"],
            "restarts": inspection["RestartCount"],
            "metrics_status": metrics_status,
            "metrics": metrics if metrics_status == 200 else None,
            "cpu": stats["CPUPerc"],
            "rss": stats["MemUsage"],
        }
    role, database, migrator = (
        env[key]
        for key in ("POSTGRES_RUNTIME_USER", "POSTGRES_DB", "POSTGRES_MIGRATION_USER")
    )
    sql = (
        "SELECT count(*),count(*) FILTER (WHERE state='active'),"
        "count(*) FILTER (WHERE wait_event_type='Lock') "
        f"FROM pg_stat_activity WHERE usename='{role}' AND datname='{database}'"
    )
    sample["db"] = compose(
        env,
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        migrator,
        "-d",
        database,
        "-Atc",
        sql,
    ).strip()
    return sample


def metrics_delta(before: dict, after: dict, services: list[str]) -> dict:
    fields = (
        "request_count",
        "error_count",
        "cache_hits",
        "cache_misses",
        "provider_calls",
        "evictions",
        "expirations",
    )
    return {
        service: {
            field: after["replicas"][service]["metrics"][field]
            - before["replicas"][service]["metrics"][field]
            for field in fields
        }
        for service in services
    }


def provider_events(env: dict[str, str], services: list[str], since: str) -> dict:
    logs = compose(
        env, "logs", "--no-color", "--timestamps", "--since", since, *services
    )
    events = []
    for line in logs.splitlines():
        if (
            "Mock generation started" not in line
            and "Mock generation finished" not in line
        ):
            continue
        match = re.search(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z", line)
        if match:
            events.append(
                (
                    datetime.fromisoformat(match.group().replace("Z", "+00:00")),
                    1 if "started" in line else -1,
                )
            )
    active = peak = starts = 0
    for _, direction in sorted(events, key=lambda item: (item[0], item[1])):
        active += direction
        peak = max(peak, active)
        starts += direction == 1
    return {
        "generation_starts": starts,
        "generation_peak": peak,
        "unfinished_at_end": active,
    }


def run_k6(
    env: dict[str, str],
    project: str,
    result_dir: Path,
    profile: str,
    vus: int,
    duration: str,
    services: list[str],
    admin: str,
    operator: str,
    *,
    burst: bool = False,
    stabilize: str | None = None,
) -> dict:
    run_id = uuid4().hex
    namespace = "capacity-test-burst" if burst else "capacity-test"
    status, _ = api(
        env, f"/api/v1/cache?namespace={namespace}", token=admin, method="DELETE"
    )
    if status != 200:
        raise RuntimeError(f"Cache clear failed: {status}")
    if not burst:
        for index in range(8):
            status, _ = api(
                env,
                "/api/v1/query",
                token=operator,
                method="POST",
                payload={
                    "prompt": f"Capacity repeated {run_id} {index}",
                    "namespace": namespace,
                },
            )
            if status != 200:
                raise RuntimeError(f"Cache warm-up failed: {status}")

    stage = f"{len(services)}rep-{profile}-{vus}vu"
    output = result_dir / stage
    output.mkdir(parents=True, exist_ok=True)
    k6_env = env | {
        "BASE_URL": "http://frontend:8080",
        "SEMANTIX_TOKEN": operator,
        "SEMANTIX_NAMESPACE": namespace,
        "PROFILE": "cold-burst" if burst else profile,
        "RUN_ID": run_id,
        "VUS": str(vus),
        "DURATION": duration,
        "LOAD_ACKNOWLEDGE_PROVIDER_CALLS": "true",
    }
    args = [
        "docker",
        "run",
        "--rm",
        "--name",
        f"{project}-k6",
        "--network",
        f"{project}_edge",
        "-v",
        f"{SCRIPT}:/scripts:ro",
        "-v",
        f"{output}:/results",
        *[
            value
            for key in (
                "BASE_URL",
                "SEMANTIX_TOKEN",
                "SEMANTIX_NAMESPACE",
                "PROFILE",
                "RUN_ID",
                "VUS",
                "DURATION",
                "LOAD_ACKNOWLEDGE_PROVIDER_CALLS",
            )
            for value in ("-e", key)
        ],
        K6_IMAGE,
        "run",
        "--summary-export",
        "/results/k6.json",
        "/scripts/capacity.js",
    ]
    if stabilize and not burst:
        warm_args = args.copy()
        warm_args[warm_args.index("--summary-export") + 1] = "/results/warmup.json"
        with (output / "warmup.log").open("w", encoding="utf-8") as warm_log:
            warm_result = subprocess.run(
                warm_args,
                cwd=ROOT,
                env=k6_env | {"DURATION": stabilize},
                stdout=warm_log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if warm_result.returncode:
            raise RuntimeError(f"{stage} stabilization run failed")
    before = snapshot(env, services, admin)
    started = datetime.now(UTC).isoformat()
    with (
        (output / "k6.log").open("w", encoding="utf-8") as log,
        (output / "telemetry.jsonl").open("w", encoding="utf-8") as telemetry,
    ):
        process = subprocess.Popen(
            args, cwd=ROOT, env=k6_env, stdout=log, stderr=subprocess.STDOUT
        )
        while process.poll() is None:
            try:
                sample = snapshot(env, services, admin)
                telemetry.write(json.dumps(sample) + "\n")
                telemetry.flush()
            except Exception as error:  # noqa: BLE001 - preserve any sampling failure as evidence
                telemetry.write(
                    json.dumps(
                        {
                            "at": datetime.now(UTC).isoformat(),
                            "sample_error": str(error),
                        }
                    )
                    + "\n"
                )
                telemetry.flush()
            time.sleep(5)
        exit_code = process.wait()
    after = snapshot(env, services, admin)
    summary = (
        json.loads((output / "k6.json").read_text(encoding="utf-8"))
        if (output / "k6.json").exists()
        else {}
    )
    metrics = summary.get("metrics", {})
    value = lambda name, key="count": metrics.get(name, {}).get(key, 0)
    probes = [
        json.loads(line)
        for line in (output / "telemetry.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    probe_failures = sum(
        "sample_error" in row
        or any(
            rep["ready_status"] != 200 or rep["health_status"] != 200
            for rep in row.get("replicas", {}).values()
        )
        for row in probes
    )
    gateway_log = compose(
        env, "logs", "--no-color", "--timestamps", "--since", started, "frontend"
    )
    gateway_errors = [
        line
        for line in gateway_log.splitlines()
        if "[error]" in line or re.search(r'" 5\d\d |status=5\d\d(?:\s|$)', line)
    ]
    (output / "gateway-errors.txt").write_text(
        "\n".join(
            gateway_errors
            if len(gateway_errors) <= 200
            else gateway_errors[:100]
            + ["... omitted middle lines ..."]
            + gateway_errors[-100:]
        )
        + "\n",
        encoding="utf-8",
    )
    failed_ids = set(re.findall(r"rid=([0-9a-f]{32})", "\n".join(gateway_errors)))
    if failed_ids:
        backend_log = compose(
            env, "logs", "--no-color", "--timestamps", "--since", started, *services
        )
        related = [
            line
            for line in backend_log.splitlines()
            if (match := re.search(r"rid=([0-9a-f]{32})", line))
            and match.group(1) in failed_ids
        ]
        (output / "backend-trace-errors.txt").write_text(
            "\n".join(
                related
                if len(related) <= 200
                else related[:100] + ["... omitted middle lines ..."] + related[-100:]
            )
            + "\n",
            encoding="utf-8",
        )
    row = {
        "topology": len(services),
        "profile": profile,
        "vus": vus,
        "duration": duration,
        "exit_code": exit_code,
        "requests": value("http_reqs"),
        "rps": value("http_reqs", "rate"),
        "success": value("capacity_status_2xx"),
        "4xx": value("capacity_status_4xx"),
        "429": value("capacity_status_429"),
        "5xx": value("capacity_status_5xx"),
        "502": value("capacity_status_502"),
        "503": value("capacity_status_503"),
        "504": value("capacity_status_504"),
        "transport": value("capacity_transport_errors"),
        "p50_ms": value("http_req_duration", "med"),
        "p95_ms": value("http_req_duration", "p(95)"),
        "p99_ms": value("http_req_duration", "p(99)"),
        "max_ms": value("http_req_duration", "max"),
        "cache_hits": value("capacity_cache_hits"),
        "cache_misses": value("capacity_cache_misses"),
        "provider_responses": value("capacity_provider_calls"),
        "coalesced_responses": value("capacity_coalesced_responses"),
        "backend_delta": metrics_delta(before, after, services),
        "provider_logs": provider_events(env, services, started),
        "db_peak": max(
            (int(row["db"].split("|")[0]) for row in probes if "db" in row), default=0
        ),
        "db_active_peak": max(
            (int(row["db"].split("|")[1]) for row in probes if "db" in row), default=0
        ),
        "db_lock_wait_peak": max(
            (int(row["db"].split("|")[2]) for row in probes if "db" in row), default=0
        ),
        "probe_failures": probe_failures,
        "sample_count": len(probes),
        "gateway_error_lines": len(gateway_errors),
    }
    (output / "result.json").write_text(
        json.dumps(row, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: row[key]
                for key in (
                    "topology",
                    "profile",
                    "vus",
                    "rps",
                    "p95_ms",
                    "5xx",
                    "transport",
                    "probe_failures",
                    "db_peak",
                )
            }
        ),
        flush=True,
    )
    return row


def environment(
    project: str, upstream: Path, admin: str, operator: str
) -> dict[str, str]:
    principals = [
        {
            "name": "capacity-admin",
            "token_sha256": hashlib.sha256(admin.encode()).hexdigest(),
            "role": "admin",
            "namespaces": ["*"],
        },
        {
            "name": "capacity-operator",
            "token_sha256": hashlib.sha256(operator.encode()).hexdigest(),
            "role": "operator",
            "namespaces": ["capacity-test", "capacity-test-burst"],
        },
    ]
    return os.environ | {
        "COMPOSE_PROJECT_NAME": project,
        "POSTGRES_DB": "semantix",
        "POSTGRES_MIGRATION_USER": "semantix_migrator",
        "POSTGRES_RUNTIME_USER": "semantix_runtime",
        "POSTGRES_MIGRATION_PASSWORD": secrets.token_urlsafe(32),
        "POSTGRES_RUNTIME_PASSWORD": secrets.token_urlsafe(32),
        "AUTH_PRINCIPALS": json.dumps(principals),
        "SEMANTIX_BIND_ADDRESS": "127.0.0.1",
        "SEMANTIX_PORT": PORT,
        "SEMANTIX_UPSTREAM_FILE": str(upstream),
        "RATE_LIMIT": RATE_LIMIT,
        "MOCK_GENERATION_DELAY_SECONDS": MOCK_DELAY,
        "EMBEDDING_PROVIDER": "mock",
        "GENERATION_PROVIDER": "mock",
        "CACHE_BACKEND": "pgvector",
        "MOCK_EMBEDDING_DIMENSIONS": "384",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", default="60s")
    parser.add_argument(
        "--profiles", nargs="+", choices=PROFILES, default=list(PROFILES)
    )
    parser.add_argument("--vus", nargs="+", type=int, default=list(LADDER))
    parser.add_argument(
        "--topologies", nargs="+", type=int, choices=(1, 2), default=[1, 2]
    )
    parser.add_argument("--skip-burst", action="store_true")
    parser.add_argument(
        "--stabilize", help="Unmeasured same-VU warm-up duration, e.g. 20s"
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    admin, operator = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    metadata = {
        "git_sha": command("git", "rev-parse", "HEAD", env=os.environ).strip(),
        "os": platform.platform(),
        "docker": command(
            "docker", "version", "--format", "{{.Server.Version}}", env=os.environ
        ).strip(),
        "docker_resources": command(
            "docker",
            "info",
            "--format",
            "{{.NCPU}}|{{.MemTotal}}|{{.OperatingSystem}}",
            env=os.environ,
        ).strip(),
        "cpu": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "k6": command(
            "docker", "run", "--rm", K6_IMAGE, "version", env=os.environ
        ).strip(),
        "backend_python": "3.14",
        "postgres_image": "pgvector/pgvector:pg17",
        "cache_backend": "pgvector",
        "embedding_dimensions": 384,
        "similarity_threshold": 0.92,
        "cache_ttl_seconds": 3600,
        "db_pool_min": 1,
        "db_pool_max": 5,
        "coordination": "postgres",
        "provider": "mock",
        "mock_generation_delay_seconds": float(MOCK_DELAY),
        "rate_limit": RATE_LIMIT,
        "think_time_seconds": "deterministic 2, 3, 4 (mean 3); burst has none",
        "duration": args.duration,
        "stabilize": args.stabilize,
        "vus": args.vus,
        "profiles": args.profiles,
    }
    (output / "environment.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    all_rows = []
    for replicas in args.topologies:
        project = f"semantix-capacity-{replicas}-{uuid4().hex[:8]}"
        existing = command(
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            "{{.ID}}",
            env=os.environ,
        )
        if existing.strip():
            raise RuntimeError(f"Refusing to reuse existing project {project}")
        with tempfile.TemporaryDirectory(
            prefix="capacity-runner-", dir=ROOT
        ) as temporary:
            upstream = Path(temporary) / "upstream.conf"
            upstream.write_text(
                "resolver 127.0.0.11 valid=5s ipv6=off;\nupstream semantix_backend {\n    zone semantix_backend 64k;\n"
                + "".join(
                    f"    server backend-{letter}:8000 resolve max_fails=2 fail_timeout=5s;\n"
                    for letter in "ab"[:replicas]
                )
                + "}\n",
                encoding="utf-8",
            )
            env = environment(project, upstream, admin, operator)
            services = [f"backend-{letter}" for letter in "ab"[:replicas]]
            try:
                if replicas == 1:
                    compose(
                        env,
                        "up",
                        "--build",
                        "-d",
                        "--wait",
                        "--wait-timeout",
                        "240",
                        "postgres",
                        "migrate",
                        "backend-a",
                    )
                    compose(env, "up", "-d", "--no-deps", "frontend")
                else:
                    compose(
                        env, "up", "--build", "-d", "--wait", "--wait-timeout", "240"
                    )
                last_error = ""
                for _ in range(40):
                    try:
                        if api(env, "/ready")[0] == 200:
                            break
                    except (OSError, ValueError) as error:
                        last_error = str(error)
                    time.sleep(1)
                else:
                    raise RuntimeError(f"Gateway never became ready: {last_error}")
                for profile in args.profiles:
                    for vus in args.vus:
                        row = run_k6(
                            env,
                            project,
                            output,
                            profile,
                            vus,
                            args.duration,
                            services,
                            admin,
                            operator,
                            stabilize=args.stabilize,
                        )
                        all_rows.append(row)
                        (output / "summary.json").write_text(
                            json.dumps(all_rows, indent=2) + "\n", encoding="utf-8"
                        )
                        if (
                            row["exit_code"]
                            or row["probe_failures"]
                            or row["5xx"] + row["transport"]
                            > max(1, row["requests"] * 0.01)
                            or row["p95_ms"] > 5000
                        ):
                            print(
                                f"Stopping {replicas}-replica {profile} ladder after degraded {vus}-VU stage",
                                flush=True,
                            )
                            break
                if not args.skip_burst:
                    burst_row = run_k6(
                        env,
                        project,
                        output,
                        "cold-burst",
                        50,
                        "0s",
                        services,
                        admin,
                        operator,
                        burst=True,
                    )
                    all_rows.append(burst_row)
                    (output / "summary.json").write_text(
                        json.dumps(all_rows, indent=2) + "\n", encoding="utf-8"
                    )
            finally:
                compose(env, "down", "--volumes", "--remove-orphans")
    print(f"Results: {output}", flush=True)


if __name__ == "__main__":
    main()
