"""Run required pytest selections and verify their collected cases against JUnit."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from xml.etree import ElementTree

import pytest

NODE_ID = "semantix_ci_nodeid"
# These consumers omit optional metadata or blocking hooks, not CacheStore duties.
OPTIONAL_SKIPS = {
    "tests/test_store_conformance.py::TestBuiltInStores::test_optional_hit_metadata[memory]": "Backend does not expose persisted hit counters/last-access",
    "tests/test_store_conformance.py::TestCompanyStore::test_optional_hit_metadata": "Backend does not expose persisted hit counters/last-access",
    "tests/test_store_conformance.py::TestCompanyStore::test_optional_busy_close_and_cancellation": "Backend lookup has no controllable asynchronous blocking boundary",
    "tests/test_store_conformance.py::TestCompanyStore::test_optional_cache_timeout_propagation": "Backend lookup has no controllable asynchronous blocking boundary",
}
# Preserve backend presence and shared-path collection without filename prefixes.
POSTGRES_REQUIRED = frozenset(
    {
        "tests/test_pgvector.py::test_owned_pool_persistence_no_implicit_ddl_and_double_close",
        "tests/test_pgvector_faults.py::test_disconnect_at_commit_never_replays_or_closes_other_pool_users[False-False]",
        "tests/test_pgvector_faults.py::test_release_finishes_before_deadline_or_cancellation_returns[True-True]",
        "tests/test_store_conformance.py::TestBuiltInStores::test_empty_exact_similar_and_threshold[pgvector]",
        "tests/test_coalescing.py::test_postgresql_confirmation_ownership_and_pool_drain",
        "tests/test_inspection.py::test_native_ttl_and_clear_all_are_separate_mutations[pgvector]",
    }
)
EMBEDDED_REQUIRED = POSTGRES_REQUIRED | frozenset(
    {
        "tests/test_redis.py::test_fresh_idempotent_concurrent_schema",
        "tests/test_sqlite.py::test_revision_lru_and_ttl_survive_reopen",
        "tests/test_inspection.py::test_redis_small_page_does_not_decode_unselected_payloads",
    }
)
REDIS_REQUIRED = frozenset(
    {
        "tests/test_redis.py::test_fresh_idempotent_concurrent_schema",
        "tests/test_redis.py::TestRedisStore::test_empty_exact_similar_and_threshold",
        "tests/test_redis_faults.py::test_real_paused_write_operation_deadline",
        "tests/test_redis_layout.py::test_inspection_leaf_failure_keeps_one_operation_and_borrowed_client[cancel]",
        "tests/test_redis_scripts.py::test_checksum_and_clear_all_composition",
        "tests/test_redis_scripts.py::test_initialization_accepts_explicit_server_identity[valkey]",
        "tests/test_redis_faults.py::test_real_suppressed_acknowledgement_never_replays[hit]",
        "tests/test_inspection.py::test_redis_small_page_does_not_decode_unselected_payloads",
    }
)
MYSQL_SERVER_REQUIRED = frozenset(
    {
        "tests/cache/api/test_mysql.py::test_concurrent_cold_requests_use_existing_coalescing",
        "tests/cache/api/test_mysql.py::test_revision_invalidated_at_actual_confirmation_boundary",
        "tests/cache/api/test_mysql.py::test_inspection_authorization_exact_totals_and_no_side_effects",
        "tests/cache/infrastructure/test_mysql.py::test_runtime_permissions_connect_only_and_cleanup",
        "tests/cache/infrastructure/test_mysql.py::test_mysql_native_work_settles_before_lifespan_exit[within_budget]",
        "tests/cache/infrastructure/test_mysql.py::test_mysql_native_work_settles_before_lifespan_exit[expiry]",
        "tests/cache/infrastructure/test_mysql.py::test_mysql_native_work_settles_before_lifespan_exit[cancel]",
    }
)
SDK_REQUIRED = frozenset(
    {
        "tests/test_integration.py::test_sync_client_crosses_real_http_query_boundary",
        "tests/test_integration.py::test_async_client_crosses_real_http_query_boundary",
        "tests/test_integration.py::test_real_http_rate_limit_without_retry_after",
        "tests/test_integration.py::test_real_http_error_headers_and_server_failure",
    }
)


class Collection:
    def __init__(self) -> None:
        self.expected: list[str] = []
        self.skipped: list[str] = []

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.skipped:
            self.skipped.append(report.nodeid)

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        # Collection is complete, including marker deselection and inherited cases.
        self.expected = [item.nodeid for item in session.items]
        for item in session.items:
            item.user_properties.append((NODE_ID, item.nodeid))


def validate(scope: str, expected: Sequence[str], report: Path) -> None:
    required = set(expected)
    if not required or len(required) != len(expected):
        raise ValueError("Empty or duplicate test collection")
    if scope == "sdk" and not required >= SDK_REQUIRED:
        raise ValueError(
            f"SDK integration cases not collected: {sorted(SDK_REQUIRED - required)}"
        )

    root = ElementTree.parse(report).getroot()  # noqa: S314 -- local report from this pytest invocation
    if root.tag not in {"testsuites", "testsuite"}:
        raise ValueError("Invalid JUnit root")
    observed: set[str] = set()
    for case in root.iter("testcase"):
        properties = case.findall(f"./properties/property[@name='{NODE_ID}']")
        if len(properties) != 1 or not properties[0].get("value"):
            raise ValueError("JUnit case has no unique collected node ID")
        node_id = properties[0].get("value", "")
        if node_id in observed or node_id not in required:
            raise ValueError(f"Duplicate or unexpected JUnit case: {node_id}")
        observed.add(node_id)
        if case.find("failure") is not None or case.find("error") is not None:
            raise ValueError(f"Required test failed or errored: {node_id}")
        skipped = case.find("skipped")
        if skipped is not None and (
            scope != "embedded" or OPTIONAL_SKIPS.get(node_id) != skipped.get("message")
        ):
            raise ValueError(f"Required test skipped: {node_id}")
    if observed != required:
        raise ValueError(
            f"Required tests missing from JUnit: {sorted(required - observed)}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scope", choices=("embedded", "postgresql", "redis", "sdk", "mysql-server")
    )
    parser.add_argument("report", type=Path)
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    pytest_args = args.pytest_args
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    collection = Collection()
    try:
        # Never accept a previous invocation's report after an interrupted run.
        args.report.unlink(missing_ok=True)
        code = pytest.main(
            [*pytest_args, "--junitxml", str(args.report)], plugins=[collection]
        )
        if code:
            return int(code)
        if collection.skipped:
            raise ValueError(f"Test collection skipped: {sorted(collection.skipped)}")
        anchors = {
            "embedded": EMBEDDED_REQUIRED,
            "postgresql": POSTGRES_REQUIRED,
            "redis": REDIS_REQUIRED,
            "mysql-server": MYSQL_SERVER_REQUIRED,
        }.get(args.scope, frozenset())
        if not set(collection.expected) >= anchors:
            raise ValueError(
                f"{args.scope.title()} integration cases not collected: {sorted(anchors - set(collection.expected))}"
            )
        validate(args.scope, collection.expected, args.report)
    except (OSError, ElementTree.ParseError, ValueError) as error:
        sys.stderr.write(f"::error::Required-test evidence rejected: {error}\n")
        return 1
    sys.stdout.write(
        f"Verified JUnit outcomes for {len(collection.expected)} collected tests.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
