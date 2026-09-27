"""Exercise a guarded 2 -> 3 -> 2 scale cycle on the disposable Compose stack."""

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from uuid import uuid4

from two_replica_smoke import (
    UPSTREAM_FILE,
    backend_logs,
    compose,
    db_connections,
    edge_ip,
    gateway_upstreams,
    provider_peak,
    query,
    request,
    run,
    set_upstream,
    wait_gateway_upstream,
)


def containers(service: str) -> set[str]:
    return set(compose("ps", "-a", "-q", service).splitlines())


def inspect(container: str, template: str) -> str:
    return run("docker", "inspect", "--format", template, container).strip()


def container_ip(container: str) -> str:
    networks = json.loads(inspect(container, "{{json .NetworkSettings.Networks}}"))
    return next(
        value["IPAddress"] for name, value in networks.items() if name.endswith("_edge")
    )


def route_to(*ips: str) -> None:
    UPSTREAM_FILE.write_text(
        "resolver 127.0.0.11 valid=5s ipv6=off;\n"
        "upstream semantix_backend {\n"
        "    zone semantix_backend 64k;\n"
        + "".join(f"    server {ip}:8000 max_fails=1 fail_timeout=5s;\n" for ip in ips)
        + "}\n",
        encoding="utf-8",
    )
    compose("exec", "-T", "frontend", "nginx", "-t")
    compose("exec", "-T", "frontend", "nginx", "-s", "reload")


def wait_routing(expected: set[str], *, excluded: frozenset[str] = frozenset()) -> None:
    # Observe gateway routing without consuming the deployment-wide API rate limit.
    path = "/health"
    seen: set[str] = set()
    clean = 0
    for _ in range(90):
        before = len(gateway_upstreams(path))
        request(path)
        served = gateway_upstreams(path)[before:]
        assert set(served) <= expected | excluded, served
        if excluded.intersection(served):
            seen.clear()
            clean = 0
        elif served:
            seen.update(served)
            clean += 1
        if clean >= 6 and expected.issubset(seen):
            return
        time.sleep(0.1)
    raise AssertionError(
        f"Gateway observed {seen}, expected {expected}, excluding {excluded}"
    )


def wait_new_replica(container: str, *, started: float) -> tuple[float, float, int]:
    db_connected = ready = None
    observed_connections = 0
    for _ in range(120):
        observed_connections = max(observed_connections, db_connections())
        if db_connected is None and observed_connections >= 3:
            db_connected = time.monotonic() - started
        if inspect(container, "{{.State.Health.Status}}") == "healthy":
            ready = time.monotonic() - started
            break
        time.sleep(0.25)
    assert db_connected is not None and ready is not None
    return db_connected, ready, observed_connections


def main() -> None:
    original_a = containers("backend-a")
    assert len(original_a) == 1
    ip_a, ip_b = edge_ip("backend-a"), edge_ip("backend-b")
    baseline_connections = db_connections()
    assert 2 <= baseline_connections <= 10
    migration = next(iter(containers("migrate")))
    migration_started = inspect(migration, "{{.State.StartedAt}}")
    original_threshold = request("/api/v1/cache/threshold", backend=ip_a)["threshold"]
    stop_traffic = Event()
    traffic_errors: list[str] = []

    def traffic() -> None:
        while not stop_traffic.is_set():
            try:
                request("/ready")
            except AssertionError as error:
                traffic_errors.append(str(error))
            stop_traffic.wait(0.15)

    with ThreadPoolExecutor(max_workers=1) as background:
        worker = background.submit(traffic)
        try:
            set_upstream("backend-b")
            wait_gateway_upstream(ip_b)
            wall_started = datetime.now(UTC)
            started = time.monotonic()
            compose(
                "up",
                "-d",
                "--no-deps",
                "--no-recreate",
                "--scale",
                "backend-a=2",
                "backend-a",
            )
            expanded = containers("backend-a")
            assert len(expanded) == 2 and original_a.issubset(expanded)
            new_container = next(iter(expanded - original_a))
            container_started = datetime.fromisoformat(
                inspect(new_container, "{{.State.StartedAt}}").replace("Z", "+00:00")
            )
            container_start_seconds = (container_started - wall_started).total_seconds()
            db_seconds, ready_seconds, startup_connections = wait_new_replica(
                new_container, started=started
            )
            ip_new = container_ip(new_container)
            assert len({ip_a, ip_b, ip_new}) == 3
            request("/ready", backend=ip_new)
            assert inspect(migration, "{{.State.StartedAt}}") == migration_started
            assert startup_connections <= 15

            first_prompt = f"scale-first-{uuid4().hex}"
            first_started = time.monotonic()
            assert query(first_prompt, backend=ip_new)["provider_called"] is True
            first_request_ms = (time.monotonic() - first_started) * 1000
            route_to(ip_a, ip_b, ip_new)
            wait_routing({ip_a, ip_b, ip_new})

            changed_threshold = 0.81 if original_threshold != 0.81 else 0.82
            request(
                "/api/v1/cache/threshold",
                backend=ip_new,
                method="PUT",
                payload={"threshold": changed_threshold},
            )
            assert (
                request("/api/v1/cache/threshold", backend=ip_a)["threshold"]
                == changed_threshold
            )

            since = datetime.now(UTC).isoformat()
            with ThreadPoolExecutor(max_workers=12) as pool:
                burst = [
                    pool.submit(
                        query, f"scale-burst-{uuid4().hex}-{index}", cache_enabled=False
                    )
                    for index in range(12)
                ]
                burst_connections = [db_connections()]
                for _ in range(3):
                    request("/ready", backend=ip_new)
                    burst_connections.append(db_connections())
                responses = [item.result(timeout=20) for item in burst]
            assert all(response["provider_called"] for response in responses)
            peak, calls = provider_peak(since)
            assert calls == 12 and 1 <= peak <= 12, (calls, peak)
            assert max(burst_connections) <= 15
            p95_ms = sorted(response["latency_ms"] for response in responses)[
                math.ceil(0.95 * len(responses)) - 1
            ]

            log_before = backend_logs("backend-a").count("Mock generation started")
            with ThreadPoolExecutor(max_workers=1) as pool:
                active = pool.submit(
                    query,
                    f"scale-drain-{uuid4().hex}",
                    backend=ip_new,
                    cache_enabled=False,
                )
                for _ in range(50):
                    if (
                        backend_logs("backend-a").count("Mock generation started")
                        > log_before
                    ):
                        break
                    time.sleep(0.1)
                else:
                    raise AssertionError("New replica did not start the drain query")
                route_to(ip_a, ip_b)
                wait_routing({ip_a, ip_b}, excluded=frozenset({ip_new}))
                assert active.result(timeout=20)["provider_called"] is True

            run("docker", "stop", "--time", "360", new_container)
            assert inspect(new_container, "{{.State.ExitCode}}") == "0"
            assert "Application shutdown complete" in backend_logs("backend-a")
            assert 1 <= db_connections() <= 10
            compose(
                "up",
                "-d",
                "--no-deps",
                "--no-recreate",
                "--scale",
                "backend-a=1",
                "backend-a",
            )
            assert containers("backend-a") == original_a
            assert query(first_prompt, backend=ip_a)["cache_hit"] is True
            assert (
                request("/api/v1/cache/threshold", backend=ip_b)["threshold"]
                == changed_threshold
            )
            request("/ready", backend=ip_a)
            request("/ready", backend=ip_b)
            assert not traffic_errors, traffic_errors[:3]
            print(
                "autoscaling verification: replicas=2->3->2 "
                f"container_start_s={container_start_seconds:.2f} "
                f"db_connect_s={db_seconds:.2f} ready_s={ready_seconds:.2f} "
                f"first_request_ms={first_request_ms:.0f} "
                f"idle_db={baseline_connections} startup_db_peak={startup_connections} "
                f"burst_db_peak={max(burst_connections)} p95_ms={p95_ms:.0f} "
                f"mock_provider_peak={peak} cold_generation_calls={calls} "
                f"routing_errors={len(traffic_errors)}"
            )
        finally:
            stop_traffic.set()
            worker.result(timeout=10)
            request(
                "/api/v1/cache/threshold",
                backend=ip_b,
                method="PUT",
                payload={"threshold": original_threshold},
            )
            set_upstream(None)


if __name__ == "__main__":
    main()
