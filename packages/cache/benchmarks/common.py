"""Deterministic fixtures, measurement summaries and dependency-free process probes."""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from typing import Any

import numpy as np

from semantix_cache import CacheEntry, EmbeddingSpace
from semantix_cache._semantics import prompt_cache_key


@dataclass(frozen=True)
class Case:
    store: str = "memory"
    workload: str = "hits"
    dimensions: int = 384
    cache_size: int = 500
    capacity: int = 5000
    concurrency: int = 1
    requests: int = 512
    threshold: float = 0.92
    ttl_seconds: float | None = 3600.0
    pool_size: int = 8
    generation_delay: float = 0.0
    seed: int = 2301
    duration: float = 60.0
    diagnostics: bool = False
    allocations: bool = False
    profile: bool = False
    worker_profile: bool = False

    def validate(self) -> None:
        if self.store not in {"memory", "pgvector", "fixture"}:
            raise ValueError("Unknown store")
        if not (
            1 <= self.dimensions <= 16000 and 0 <= self.cache_size <= self.capacity
        ):
            raise ValueError("Invalid dimension/cache size")
        ceiling = 100000 if self.store == "pgvector" else 5000
        if not (1 <= self.capacity <= ceiling and 1 <= self.concurrency <= 128):
            raise ValueError("Invalid capacity/concurrency")
        if not (1 <= self.requests <= 100000 and 1 <= self.pool_size <= 100):
            raise ValueError("Invalid request/pool bound")
        if not (0 <= self.threshold <= 1 and 0 <= self.generation_delay <= 10):
            raise ValueError("Invalid threshold/provider delay")
        if self.profile and self.worker_profile:
            raise ValueError("Run main-thread and worker profiles in separate trials")
        if self.worker_profile and (self.store != "memory" or not self.diagnostics):
            raise ValueError("Worker profiles require diagnostic MemoryStore trials")
        if (
            self.cache_size + self.requests + self.concurrency + 16
        ) * self.dimensions > 32_000_000:
            raise ValueError("Fixture exceeds bounded benchmark component budget")
        if not (0 < self.duration <= 3600):
            raise ValueError("Invalid stability duration")


class Dataset:
    """Seeded isotropic float64 unit vectors, materialized outside timed regions.

    Tuples deliberately exercise the current public provider/store representation.
    This synthetic corpus tests exact reuse and known misses, not semantic quality.
    The digest identifies the generated array and must match across repeat trials.
    """

    def __init__(self, case: Case) -> None:
        count = case.cache_size + case.requests + case.concurrency + 16
        matrix = np.random.default_rng(case.seed).standard_normal(
            (count, case.dimensions)
        )
        matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
        self.digest = hashlib.sha256(matrix.tobytes()).hexdigest()
        self.vectors = [tuple(row.tolist()) for row in matrix]
        self.space = EmbeddingSpace(
            identity=f"benchmark-isotropic-v1:seed{case.seed}:d{case.dimensions}",
            dimensions=case.dimensions,
        )

    @staticmethod
    def prompt(index: int) -> str:
        return f"synthetic-question-{index:08d}"

    @staticmethod
    def response(prompt: str) -> str:
        return "synthetic-answer:" + prompt

    def entry(self, index: int, namespace: str = "benchmark") -> CacheEntry:
        prompt = self.prompt(index)
        return CacheEntry(
            cache_key=prompt_cache_key(prompt, namespace=namespace),
            namespace=namespace,
            prompt=prompt,
            response=self.response(prompt),
            embedding=self.vectors[index],
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
        )


class Embedder:
    def __init__(self, dataset: Dataset) -> None:
        self.dataset = dataset
        self.calls = 0

    @property
    def embedding_space(self) -> EmbeddingSpace:
        return self.dataset.space

    async def embed(self, text: str) -> Sequence[float]:
        self.calls += 1
        return self.dataset.vectors[int(text.rsplit("-", 1)[1])]


class Generator:
    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls = 0
        self.prompts: set[str] = set()

    async def __call__(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.add(prompt)
        if self.delay:
            await asyncio.sleep(self.delay)
        return Dataset.response(prompt)


def summary(samples_ns: Sequence[int], elapsed: float) -> dict[str, Any]:
    ordered = sorted(samples_ns)

    def quantile(p: float) -> float:
        if not ordered:
            return 0.0
        rank = (len(ordered) - 1) * p
        lower, upper = math.floor(rank), math.ceil(rank)
        value = ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)
        return value / 1_000_000

    return {
        "operations": len(ordered),
        "elapsed_seconds": elapsed,
        "operations_per_second": len(ordered) / elapsed if elapsed else 0.0,
        "latency_ms": {
            "p50": quantile(0.5),
            "p95": quantile(0.95),
            "p99": quantile(0.99),
            "max": quantile(1.0),
        },
        "tail_warning": "Fewer than 1000 samples; P99 is descriptive, not a stable budget"
        if len(ordered) < 1000
        else None,
    }


def rss_bytes() -> dict[str, int | None]:
    if sys.platform == "win32":

        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
                (name, ctypes.c_size_t)
                for name in (
                    "peak",
                    "working",
                    "paged_peak",
                    "paged",
                    "nonpaged_peak",
                    "nonpaged",
                    "pagefile",
                    "pagefile_peak",
                    "private",
                )
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
        ]
        if psapi.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            return {
                "rss": counters.working,
                "peak_rss": counters.peak,
                "private_bytes": counters.private,
            }
    elif Path("/proc/self/status").exists():
        values = {}
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                key, value, *_ = line.split()
                values[key] = int(value) * 1024
        return {
            "rss": values.get("VmRSS:"),
            "peak_rss": values.get("VmHWM:"),
            "private_bytes": None,
        }
    return {"rss": None, "peak_rss": None, "private_bytes": None}


def environment(case: Case) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    cpu = platform.processor()
    ram: int | None = None
    if sys.platform == "win32":
        import winreg  # noqa: PLC0415 -- Windows-only standard library

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        ) as key:
            cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()

        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong)
                for name in (
                    "total",
                    "available",
                    "page_total",
                    "page_available",
                    "virtual_total",
                    "virtual_available",
                    "extended",
                )
            ]

        memory = Memory()
        memory.length = ctypes.sizeof(memory)
        if ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(memory)):
            ram = memory.total
    elif Path("/proc/meminfo").exists():
        ram = int(Path("/proc/meminfo").read_text().splitlines()[0].split()[1]) * 1024
        if Path("/proc/cpuinfo").exists():
            cpu = next(
                (
                    line.split(":", 1)[1].strip()
                    for line in Path("/proc/cpuinfo").read_text().splitlines()
                    if line.startswith("model name")
                ),
                cpu,
            )
    source = root / "packages/cache/src/semantix_cache"
    hashes = {
        str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(
            p.read_bytes()
        ).hexdigest()
        for p in sorted(source.rglob("*.py"))
    }
    return {
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"],  # noqa: S607 -- fixed read-only git tool
            cwd=root,
            encoding="utf-8",
        ).strip(),
        "runtime_source_sha256": hashes,
        "benchmark_source_sha256": {
            str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in sorted(Path(__file__).parent.glob("*.py"))
        },
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "ram_bytes": ram,
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "python": sys.version,
        "versions": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pydantic", "semantix-cache")
        },
        "blas_environment": {
            name: os.environ.get(name)
            for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
        },
        "numpy_build": np.show_config(mode="dicts"),
        "process_topology": "one fresh Python worker/event loop per trial; MemoryStore uses its existing numerical thread; database is external",
        "measurement": "perf_counter_ns; closed-loop workers; linear-interpolated quantiles; setup/warmup/cleanup excluded",
        "gc_enabled": __import__("gc").isenabled(),
        "case": asdict(case),
    }


def write_result(path: Path, result: dict[str, Any]) -> None:
    """Refuse raw evidence outside Git-ignored paths, including nonexistent files."""
    path = path.resolve()
    check = subprocess.run(["git", "check-ignore", "--quiet", str(path)], check=False)  # noqa: S603, S607 -- fixed local git command
    if check.returncode != 0:
        raise ValueError("Raw output must be in a Git-ignored directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def now_ns() -> int:
    return perf_counter_ns()
