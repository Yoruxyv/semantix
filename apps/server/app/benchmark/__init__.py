"""Controlled evaluation datasets, execution and reproducibility evidence.

Evaluations use a fresh isolated in-memory cache; they neither read nor seed the
live application cache. Provider configuration is shared, so deterministic mock
providers are the repeatable default for tests and local comparisons.

``api`` owns evaluation, dataset, history and comparison HTTP contracts. ``domain``
contains dataset validation, workload/result models, metrics and repository ports.
``application.service`` composes the bounded runner and catalogs; ``run_executor``
executes workloads, while reproducibility and comparison modules describe safe
configuration/evidence compatibility. ``infrastructure`` implements optional
PostgreSQL dataset/history persistence and owns the corresponding SQL migrations.

The lifespan supplies embedding/generation resources and optional repositories.
Preserve namespace authorization, bounded serialized execution, complete metric
accounting and separation from live cache state. This server evaluation subsystem
is distinct from benchmarks of the embedded runtime's own latency/throughput.
Start with ``docs/guides/benchmarking.md``, the service/domain contracts and matching
benchmark tests before changing result or persisted dataset/history schemas.
"""
