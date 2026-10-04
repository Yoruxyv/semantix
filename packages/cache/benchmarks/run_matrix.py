"""Execute checked-in workload groups sequentially, using fresh worker processes.

No network providers are called. Set BLAS thread counts before worker imports.
Raw outputs and child logs must remain in a Git-ignored directory.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def expand(group: dict[str, Any], defaults: dict[str, Any]) -> list[dict[str, Any]]:
    axes = group.get("axes", {})
    keys = list(axes)
    cases = []
    for values in itertools.product(*(axes[key] for key in keys)):
        case = {
            **defaults,
            **group.get("case", {}),
            **dict(zip(keys, values, strict=True)),
        }
        if case.get("workload") == "burst" and "generation_delay" not in case:
            case["generation_delay"] = group.get("burst_delay", 0.02)
        cases.append(case)
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan", type=Path, default=Path(__file__).with_name("workloads.json")
    )
    parser.add_argument("--group", action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--blas-threads", default="1")
    parser.add_argument("--store", choices=["memory", "pgvector", "fixture"])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--disposable-database", action="store_true")
    args = parser.parse_args()
    check = subprocess.run(  # noqa: S603 -- fixed git tool, literal args, no shell
        [  # noqa: S607 -- use the installed git tool
            "git",
            "check-ignore",
            "--quiet",
            str((args.output_dir / "probe.json").resolve()),
        ],
        check=False,
    )
    if check.returncode:
        parser.error("Output directory must be Git-ignored")
    if args.blas_threads != "default" and not 1 <= int(args.blas_threads) <= 128:
        parser.error("Invalid BLAS thread count")
    env = os.environ.copy()
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        if args.blas_threads == "default":
            env.pop(key, None)
        else:
            env[key] = args.blas_threads
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name in args.group:
        group = plan["groups"][name]
        cases = expand(group, plan["defaults"])
        for index, case in enumerate(cases):
            if args.store and case.get("store", "memory") != args.store:
                continue
            if case.get("store") == "pgvector" and not args.disposable_database:
                parser.error("PostgreSQL requires --disposable-database")
            for repeat in range(group.get("repeats", 3)):
                digest = hashlib.sha256(
                    json.dumps(case, sort_keys=True).encode()
                ).hexdigest()[:12]
                target = args.output_dir / f"{name}-{digest}-r{repeat}.json"
                if target.exists():
                    existing = json.loads(target.read_text(encoding="utf-8"))
                    if args.resume and existing.get("correctness_passed"):
                        continue
                    raise FileExistsError(
                        f"Retain prior evidence and use a new output directory: {target}"
                    )
                module = group.get("module", "runtime")
                command = [
                    sys.executable,
                    "-m",
                    "benchmarks." + module,
                    "--case-json",
                    json.dumps(case),
                    "--output",
                    str(target),
                ]
                if module == "numerics":
                    command += ["--iterations", str(group.get("iterations", 30))]
                elif case.get("store") == "pgvector":
                    command.append("--disposable-database")
                completed = subprocess.run(  # noqa: S603 -- local module/arguments, no shell
                    command, env=env, capture_output=True, encoding="utf-8", check=False
                )
                target.with_suffix(".log").write_text(
                    completed.stdout + completed.stderr, encoding="utf-8"
                )
                if completed.returncode:
                    raise RuntimeError(
                        f"Trial failed; inspect ignored evidence: {target.with_suffix('.log')}"
                    )
            print(f"{name}: {index + 1}/{len(cases)} cases completed", flush=True)  # noqa: T201 -- benchmark progress interface


if __name__ == "__main__":
    main()
