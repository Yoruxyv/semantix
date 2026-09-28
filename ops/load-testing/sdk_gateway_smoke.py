"""Verify the Python SDK through a disposable two-replica gateway."""

import argparse
import hashlib
import json
import secrets
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from capacity_runner import PORT, ROOT, compose, direct, environment
from semantix_client import (
    SemantixClient,
    SemantixRateLimitError,
    SemantixServerError,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    project = f"semantix-capacity-sdk-{uuid4().hex[:8]}"
    admin, operator, sdk_token = (secrets.token_urlsafe(32) for _ in range(3))
    base = f"http://127.0.0.1:{PORT}"
    evidence = {
        "sync": False,
        "async": False,
        "shared_cache": False,
        "shared_threshold": False,
        "failover_recovery": False,
        "rate_limit_429": False,
        "server_5xx": False,
    }
    with tempfile.TemporaryDirectory(
        prefix="capacity-runner-sdk-", dir=ROOT
    ) as temporary:
        upstream = Path(temporary) / "upstream.conf"
        upstream.write_text(
            (ROOT / "frontend/upstream.prod.conf").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        env = environment(project, upstream, admin, operator)
        principals = json.loads(env["AUTH_PRINCIPALS"])
        principals.append(
            {
                "name": "capacity-sdk",
                "token_sha256": hashlib.sha256(sdk_token.encode()).hexdigest(),
                "role": "operator",
                "namespaces": [
                    "normal",
                    "read-only",
                    "refresh",
                    "bypass",
                    "private",
                    "async",
                ],
            }
        )
        env["AUTH_PRINCIPALS"] = json.dumps(principals)
        try:
            compose(env, "up", "--build", "-d", "--wait", "--wait-timeout", "240")
            test_env = env | {
                "SEMANTIX_INTEGRATION_URL": base,
                "SEMANTIX_INTEGRATION_TOKEN": sdk_token,
            }
            result = subprocess.run(
                [
                    str(ROOT / "sdk/.venv/Scripts/python.exe"),
                    "-m",
                    "pytest",
                    "sdk/tests/test_integration.py",
                    "-q",
                ],
                cwd=ROOT,
                env=test_env,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(
                    f"SDK gateway integration failed: {result.stdout[-1200:]} {result.stderr[-500:]}"
                )
            evidence["sync"] = evidence["async"] = True

            prompt = f"sdk shared cache {uuid4().hex}"
            first = direct(
                env,
                "backend-a",
                "/api/v1/query",
                admin,
                method="POST",
                payload={"prompt": prompt, "namespace": "capacity-test"},
            )
            second = direct(
                env,
                "backend-b",
                "/api/v1/query",
                admin,
                method="POST",
                payload={"prompt": prompt, "namespace": "capacity-test"},
            )
            assert first[0] == second[0] == 200 and second[1]["cache_hit"] is True
            evidence["shared_cache"] = True
            threshold = direct(env, "backend-a", "/api/v1/cache/threshold", admin)[1][
                "threshold"
            ]
            updated = 0.81 if threshold != 0.81 else 0.82
            assert (
                direct(
                    env,
                    "backend-a",
                    "/api/v1/cache/threshold",
                    admin,
                    method="PUT",
                    payload={"threshold": updated},
                )[0]
                == 200
            )
            assert (
                direct(env, "backend-b", "/api/v1/cache/threshold", admin)[1][
                    "threshold"
                ]
                == updated
            )
            direct(
                env,
                "backend-b",
                "/api/v1/cache/threshold",
                admin,
                method="PUT",
                payload={"threshold": threshold},
            )
            evidence["shared_threshold"] = True

            compose(env, "stop", "backend-a")
            time.sleep(6)
            with SemantixClient(base_url=base, token=sdk_token) as client:
                client.query(f"sdk failover {uuid4().hex}", namespace="normal")
            compose(env, "up", "-d", "--wait", "--wait-timeout", "120", "backend-a")
            assert direct(env, "backend-a", "/ready")[0] == 200
            with SemantixClient(base_url=base, token=sdk_token) as client:
                client.query(f"sdk recovery {uuid4().hex}", namespace="normal")
            evidence["failover_recovery"] = True

            limited = env | {"RATE_LIMIT": "2/minute"}
            compose(
                limited,
                "up",
                "-d",
                "--no-deps",
                "--force-recreate",
                "--wait",
                "--wait-timeout",
                "120",
                "backend-a",
                "backend-b",
            )
            with SemantixClient(base_url=base, token=operator) as client:
                for index in range(2):
                    client.query(
                        f"sdk capacity limit {index}", namespace="capacity-test"
                    )
                try:
                    client.query("sdk capacity limit 2", namespace="capacity-test")
                except SemantixRateLimitError as error:
                    assert error.status_code == 429
                    evidence["rate_limit_429"] = True
                else:
                    raise AssertionError(
                        "The third request exceeded the shared 2/minute quota without HTTP 429"
                    )

            compose(limited, "stop", "postgres")
            time.sleep(1)
            with SemantixClient(base_url=base, token=operator) as client:
                try:
                    client.query(
                        "sdk capacity database outage", namespace="capacity-test"
                    )
                except SemantixServerError as error:
                    assert error.status_code >= 500
                    evidence["server_5xx"] = True
                else:
                    raise AssertionError(
                        "The disposable database outage did not produce a server error"
                    )
            compose(limited, "start", "postgres")
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
                )
            print(json.dumps(evidence), flush=True)
        finally:
            compose(env, "down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
