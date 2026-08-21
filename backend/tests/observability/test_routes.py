from hashlib import sha256
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.exceptions import CacheStorageError
from app.factory import create_app

VIEWER_TOKEN = "metrics-viewer-secret"
OPERATOR_TOKEN = "metrics-operator-secret"
NAMESPACE_ADMIN_TOKEN = "metrics-namespace-admin-secret"
GLOBAL_ADMIN_TOKEN = "metrics-global-admin-secret"
FAKE_API_KEY = "recognizable-diagnostics-api-key"
FAKE_DATABASE_URL = (
    "postgresql://diagnostic-user:diagnostic-password@private-db.internal:5432/semantix"
)
FAKE_PROVIDER_URL = "https://private-provider.internal/v1"
FAKE_MODEL = "private-model/diagnostics-must-not-leak"
FAKE_PROMPT = "recognizable private diagnostics prompt"
FAKE_NAMESPACE = "recognizable-private-namespace"
FAKE_DATASET_NAME = "Recognizable private diagnostics dataset"


def _token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _secured_settings() -> Settings:
    return Settings(
        embedding_provider="mock",
        generation_provider="mock",
        mock_embedding_dimensions=32,
        hf_api_key=FAKE_API_KEY,
        hf_inference_base_url=FAKE_PROVIDER_URL,
        hf_chat_base_url=FAKE_PROVIDER_URL,
        hf_embedding_model=FAKE_MODEL,
        hf_generation_model=FAKE_MODEL,
        openai_base_url=FAKE_PROVIDER_URL,
        openai_embedding_model=FAKE_MODEL,
        openai_generation_model=FAKE_MODEL,
        cache_backend="memory",
        cache_ttl_seconds=None,
        database_url=FAKE_DATABASE_URL,
        allowed_origins=["https://private-ui.internal"],
        rate_limit="1000/minute",
        auth_mode="token",
        auth_principals=[
            {
                "name": "metrics-viewer",
                "token_sha256": _token_hash(VIEWER_TOKEN),
                "role": "viewer",
                "namespaces": ["tenant-alpha"],
            },
            {
                "name": "metrics-operator",
                "token_sha256": _token_hash(OPERATOR_TOKEN),
                "role": "operator",
                "namespaces": ["tenant-alpha"],
            },
            {
                "name": "metrics-namespace-admin",
                "token_sha256": _token_hash(NAMESPACE_ADMIN_TOKEN),
                "role": "admin",
                "namespaces": ["tenant-alpha"],
            },
            {
                "name": "metrics-global-admin",
                "token_sha256": _token_hash(GLOBAL_ADMIN_TOKEN),
                "role": "admin",
                "namespaces": ["*"],
            },
        ],
    )


def test_metrics_endpoint_reports_live_query_and_cache_counters() -> None:
    settings = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        mock_embedding_dimensions=32,
        cache_backend="memory",
        max_cache_size=1,
        cache_ttl_seconds=None,
        hf_api_key=None,
        prompt_typo_correction_enabled=False,
        allowed_origins=["http://localhost:5173"],
        rate_limit="1000/minute",
    )

    with TestClient(create_app(settings)) as client:
        initial = client.get("/api/v1/metrics")
        assert initial.status_code == 200
        assert initial.json() == {
            "observed_at": initial.json()["observed_at"],
            "uptime_seconds": initial.json()["uptime_seconds"],
            "request_count": 0,
            "error_count": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "provider_calls": 0,
            "in_flight_coalesced_requests": 0,
            "average_latency_ms": None,
            "p95_latency_ms": None,
            "latency_sample_size": 0,
            "cache_size": 0,
            "evictions": 0,
            "expirations": 0,
        }

        miss = client.post(
            "/api/v1/query",
            json={"prompt": "metrics alpha"},
        )
        assert miss.status_code == 200
        assert miss.json()["cache_hit"] is False

        hit = client.post("/api/v1/query", json={"prompt": "metrics alpha"})
        assert hit.status_code == 200
        assert hit.json()["cache_hit"] is True

        bypassed = client.post(
            "/api/v1/query",
            json={
                "prompt": "metrics beta",
                "cache_read_enabled": False,
            },
        )
        assert bypassed.status_code == 200

        response = client.get("/api/v1/metrics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_count"] == 3
    assert payload["error_count"] == 0
    assert payload["cache_hits"] == 1
    assert payload["cache_misses"] == 1
    assert payload["provider_calls"] == 2
    assert payload["in_flight_coalesced_requests"] == 0
    assert payload["average_latency_ms"] >= 0
    assert payload["p95_latency_ms"] >= 0
    assert payload["latency_sample_size"] == 3
    assert payload["cache_size"] == 1
    assert payload["evictions"] == 1
    assert payload["expirations"] == 0


@pytest.mark.parametrize(
    "token",
    [
        VIEWER_TOKEN,
        OPERATOR_TOKEN,
        NAMESPACE_ADMIN_TOKEN,
    ],
    ids=["scoped-viewer", "scoped-operator", "namespace-admin"],
)
def test_metrics_rejects_non_global_principals_without_leaking_foreign_activity(
    token: str,
) -> None:
    with TestClient(create_app(_secured_settings())) as client:
        created = client.post(
            "/api/v1/query",
            headers=_authorization(GLOBAL_ADMIN_TOKEN),
            json={
                "prompt": "foreign metrics activity",
                "namespace": "tenant-beta",
            },
        )
        scoped_cache_stats = client.get(
            "/api/v1/cache/stats",
            headers=_authorization(token),
        )
        response = client.get(
            "/api/v1/metrics",
            headers=_authorization(token),
        )

    assert created.status_code == 200
    assert scoped_cache_stats.status_code == 200
    assert scoped_cache_stats.json()["size"] == 0
    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"
    assert "request_count" not in response.text
    assert "cache_size" not in response.text


def test_metrics_requires_authentication_when_token_auth_is_enabled() -> None:
    with TestClient(create_app(_secured_settings())) as client:
        response = client.get("/api/v1/metrics")

    assert response.status_code == 401
    assert response.json()["error"] == "authentication_required"


def test_global_admin_receives_unchanged_global_metrics_snapshot() -> None:
    with TestClient(create_app(_secured_settings())) as client:
        created = client.post(
            "/api/v1/query",
            headers=_authorization(GLOBAL_ADMIN_TOKEN),
            json={
                "prompt": "foreign metrics activity",
                "namespace": "tenant-beta",
            },
        )
        response = client.get(
            "/api/v1/metrics",
            headers=_authorization(GLOBAL_ADMIN_TOKEN),
        )

    assert created.status_code == 200
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_count"] == 1
    assert payload["cache_misses"] == 1
    assert payload["provider_calls"] == 1
    assert payload["cache_size"] == 1


def test_global_admin_receives_only_allowlisted_runtime_diagnostics() -> None:
    app = create_app(_secured_settings())

    with TestClient(app) as client:
        live_query = client.post(
            "/api/v1/query",
            headers=_authorization(GLOBAL_ADMIN_TOKEN),
            json={"prompt": FAKE_PROMPT, "namespace": FAKE_NAMESPACE},
        )
        evaluation = client.post(
            "/api/v1/evaluations/runs",
            headers=_authorization(GLOBAL_ADMIN_TOKEN),
            json={
                "dataset_source": {
                    "kind": "inline",
                    "definition": {
                        "schema_version": 1,
                        "name": FAKE_DATASET_NAME,
                        "cases": [
                            {
                                "case_id": "private-seed",
                                "prompt": FAKE_PROMPT,
                                "expected_cache_hit": False,
                            },
                            {
                                "case_id": "private-repeat",
                                "prompt": FAKE_PROMPT,
                                "expected_cache_hit": True,
                                "expected_match_case_id": "private-seed",
                            },
                        ],
                    },
                },
                "evaluation_thresholds": [0.8, 0.92],
                "allow_external_provider_calls": True,
            },
        )
        response = client.get(
            "/api/v1/diagnostics",
            headers=_authorization(GLOBAL_ADMIN_TOKEN),
        )

    assert live_query.status_code == 200
    assert evaluation.status_code == 200
    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "observed_at": payload["observed_at"],
        "process_scope": "single_backend_process",
        "application_version": "1.0.0",
        "embedding_provider_category": "mock",
        "generation_provider_category": "mock",
        "embedding_dimensions": 32,
        "embedding_space_fingerprint": payload["embedding_space_fingerprint"],
        "generation_configuration_fingerprint": (
            payload["generation_configuration_fingerprint"]
        ),
        "cache_backend": "memory",
        "cache_readiness": "ready",
        "normalization_mode": "identity",
        "normalization_algorithm_version": "identity-v1",
        "normalization_fingerprint": payload["normalization_fingerprint"],
        "evaluation_timeout_seconds": 300.0,
        "evaluation_max_cases": 50,
        "evaluation_max_repetitions": 5,
        "evaluation_max_thresholds": 15,
        "evaluation_max_request_bytes": 65_536,
        "evaluation_dataset_persistence_enabled": False,
        "evaluation_history_persistence_enabled": False,
    }
    reproducibility = evaluation.json()["reproducibility"]
    assert (
        payload["embedding_space_fingerprint"]
        == (reproducibility["embedding_space_fingerprint"])
    )
    assert (
        payload["generation_configuration_fingerprint"]
        == (reproducibility["generation_configuration_fingerprint"])
    )
    assert (
        payload["normalization_fingerprint"]
        == (reproducibility["normalization_fingerprint"])
    )

    forbidden_values = (
        FAKE_API_KEY,
        _token_hash(GLOBAL_ADMIN_TOKEN),
        FAKE_DATABASE_URL,
        "diagnostic-password",
        FAKE_PROVIDER_URL,
        FAKE_MODEL,
        FAKE_PROMPT,
        f"[mock provider] {FAKE_PROMPT}",
        FAKE_NAMESPACE,
        FAKE_DATASET_NAME,
        evaluation.json()["run_id"],
    )
    assert all(value not in response.text for value in forbidden_values)


@pytest.mark.parametrize(
    "token",
    [VIEWER_TOKEN, OPERATOR_TOKEN, NAMESPACE_ADMIN_TOKEN],
    ids=["scoped-viewer", "scoped-operator", "namespace-admin"],
)
def test_diagnostics_rejects_non_global_principals(token: str) -> None:
    with TestClient(create_app(_secured_settings())) as client:
        response = client.get(
            "/api/v1/diagnostics",
            headers=_authorization(token),
        )

    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"
    assert "embedding_space_fingerprint" not in response.text


def test_diagnostics_requires_authentication_when_token_auth_is_enabled() -> None:
    with TestClient(create_app(_secured_settings())) as client:
        response = client.get("/api/v1/diagnostics")

    assert response.status_code == 401
    assert response.json()["error"] == "authentication_required"


def test_diagnostics_retains_auth_disabled_local_access() -> None:
    settings = Settings(
        embedding_provider="mock",
        generation_provider="mock",
        mock_embedding_dimensions=32,
        cache_backend="memory",
        cache_ttl_seconds=None,
        hf_api_key=None,
        allowed_origins=["http://localhost:5173"],
        rate_limit="1000/minute",
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/diagnostics")

    assert response.status_code == 200
    assert response.json()["process_scope"] == "single_backend_process"


def test_diagnostics_reports_cache_unavailability_without_leaking_details() -> None:
    app = create_app(_secured_settings())

    with TestClient(app) as client:
        app.state.semantic_cache.stats = AsyncMock(
            side_effect=CacheStorageError("private storage failure")
        )
        response = client.get(
            "/api/v1/diagnostics",
            headers=_authorization(GLOBAL_ADMIN_TOKEN),
        )

    assert response.status_code == 200
    assert response.json()["cache_readiness"] == "unavailable"
    assert "private storage failure" not in response.text
