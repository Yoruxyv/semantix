from hashlib import sha256

from fastapi.testclient import TestClient

from app.cache.domain.keys import prompt_cache_key
from app.core.config import Settings
from app.factory import create_app
from tests.benchmark.api.test_routes import Provider, benchmark_service
from tests.benchmark.support import InMemoryEvaluationDatasetRepository

VIEWER_TOKEN = "viewer-secret"
OPERATOR_TOKEN = "operator-secret"
ADMIN_TOKEN = "admin-secret"
NAMESPACE_ADMIN_TOKEN = "namespace-admin-secret"
MULTI_OPERATOR_TOKEN = "multi-operator-secret"


def token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def settings(*, rate_limit: str = "20/minute") -> Settings:
    return Settings(
        embedding_provider="mock",
        generation_provider="mock",
        hf_api_key=None,
        cache_backend="memory",
        allowed_origins=["http://localhost:5173"],
        rate_limit=rate_limit,
        auth_mode="token",
        auth_principals=[
            {
                "name": "reader",
                "token_sha256": token_hash(VIEWER_TOKEN),
                "role": "viewer",
                "namespaces": ["default"],
            },
            {
                "name": "operator",
                "token_sha256": token_hash(OPERATOR_TOKEN),
                "role": "operator",
                "namespaces": ["default"],
            },
            {
                "name": "administrator",
                "token_sha256": token_hash(ADMIN_TOKEN),
                "role": "admin",
                "namespaces": ["*"],
            },
            {
                "name": "namespace-administrator",
                "token_sha256": token_hash(NAMESPACE_ADMIN_TOKEN),
                "role": "admin",
                "namespaces": ["default"],
            },
            {
                "name": "multi-operator",
                "token_sha256": token_hash(MULTI_OPERATOR_TOKEN),
                "role": "operator",
                "namespaces": ["tenant-a", "tenant-b"],
            },
        ],
    )


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_auth_config_is_public_and_does_not_disclose_principals() -> None:
    with TestClient(create_app(settings())) as client:
        response = client.get("/api/v1/auth/config")

    assert response.status_code == 200
    assert response.json() == {"authentication_required": True}
    assert "reader" not in response.text


def test_auth_config_is_not_subject_to_the_application_rate_limit() -> None:
    with TestClient(create_app(settings(rate_limit="1/minute"))) as client:
        responses = [client.get("/api/v1/auth/config") for _ in range(25)]

    assert all(response.status_code == 200 for response in responses)
    assert all(
        response.json() == {"authentication_required": True} for response in responses
    )


def test_protected_routes_require_a_valid_token() -> None:
    with TestClient(create_app(settings())) as client:
        response = client.get("/api/v1/cache/stats")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"] == "authentication_required"


def test_viewer_can_read_its_namespace_but_cannot_clear_cache() -> None:
    with TestClient(create_app(settings())) as client:
        read_response = client.get(
            "/api/v1/cache/stats",
            headers=authorization(VIEWER_TOKEN),
        )
        clear_response = client.delete(
            "/api/v1/cache",
            headers=authorization(VIEWER_TOKEN),
        )

    assert read_response.status_code == 200
    assert clear_response.status_code == 403


def test_viewer_cannot_submit_live_queries() -> None:
    with TestClient(create_app(settings())) as client:
        response = client.post(
            "/api/v1/query",
            headers=authorization(VIEWER_TOKEN),
            json={"prompt": "Explain semantic caching"},
        )

    assert response.status_code == 403


def test_operator_can_submit_queries_for_an_authorized_namespace() -> None:
    with TestClient(create_app(settings())) as client:
        response = client.post(
            "/api/v1/query",
            headers=authorization(OPERATOR_TOKEN),
            json={"prompt": "Explain semantic caching", "namespace": "default"},
        )

    assert response.status_code == 200


def test_operator_cannot_escape_its_namespace_scope() -> None:
    with TestClient(create_app(settings())) as client:
        response = client.post(
            "/api/v1/query",
            headers=authorization(OPERATOR_TOKEN),
            json={"prompt": "Explain semantic caching", "namespace": "other"},
        )

    assert response.status_code == 403


def test_query_namespace_selection_covers_multiple_and_wildcard_scopes() -> None:
    with TestClient(create_app(settings())) as client:
        missing_selection = client.post(
            "/api/v1/query",
            headers=authorization(MULTI_OPERATOR_TOKEN),
            json={"prompt": "Explain semantic caching"},
        )
        selected = client.post(
            "/api/v1/query",
            headers=authorization(MULTI_OPERATOR_TOKEN),
            json={
                "prompt": "Explain semantic caching",
                "namespace": "tenant-b",
            },
        )
        wildcard_explicit = client.post(
            "/api/v1/query",
            headers=authorization(ADMIN_TOKEN),
            json={
                "prompt": "Explain semantic caching",
                "namespace": "tenant-c",
            },
        )

    assert missing_selection.status_code == 403
    assert selected.status_code == 200
    assert wildcard_explicit.status_code == 200


def test_benchmark_dataset_and_run_roles_match_viewer_operator_capabilities() -> None:
    with TestClient(create_app(settings())) as client:
        catalog = client.get(
            "/api/v1/benchmarks/datasets",
            headers=authorization(VIEWER_TOKEN),
        )
        viewer_run = client.post(
            "/api/v1/benchmarks/run",
            headers=authorization(VIEWER_TOKEN),
            json={"allow_external_provider_calls": True},
        )
        operator_run = client.post(
            "/api/v1/benchmarks/run",
            headers=authorization(OPERATOR_TOKEN),
            json={"allow_external_provider_calls": True},
        )

    assert catalog.status_code == 200
    assert viewer_run.status_code == 403
    assert operator_run.status_code == 200


def test_evaluation_import_roles_match_viewer_operator_capabilities() -> None:
    definition = {
        "schema_version": 1,
        "name": "Authorization set",
        "cases": [
            {
                "case_id": "case",
                "prompt": "Synthetic authorization prompt",
                "expected_cache_hit": False,
            }
        ],
    }
    with TestClient(create_app(settings())) as client:
        viewer_catalog = client.get(
            "/api/v1/evaluations/datasets",
            headers=authorization(VIEWER_TOKEN),
        )
        viewer_validate = client.post(
            "/api/v1/evaluations/datasets/validate",
            headers=authorization(VIEWER_TOKEN),
            json={"dataset": definition},
        )
        operator_validate = client.post(
            "/api/v1/evaluations/datasets/validate",
            headers=authorization(OPERATOR_TOKEN),
            json={"dataset": definition},
        )
        viewer_run = client.post(
            "/api/v1/evaluations/runs",
            headers=authorization(VIEWER_TOKEN),
            json={
                "dataset_source": {
                    "kind": "inline",
                    "definition": definition,
                },
                "allow_external_provider_calls": True,
            },
        )
        operator_run = client.post(
            "/api/v1/evaluations/runs",
            headers=authorization(OPERATOR_TOKEN),
            json={
                "dataset_source": {
                    "kind": "inline",
                    "definition": definition,
                },
                "allow_external_provider_calls": True,
            },
        )

    assert viewer_catalog.status_code == 200
    assert viewer_validate.status_code == viewer_run.status_code == 403
    assert operator_validate.status_code == 200
    assert operator_run.status_code == 200


def test_builtin_history_namespace_follows_existing_scope_rules() -> None:
    app = create_app(settings())
    with TestClient(app) as client:
        app.state.benchmark_service = benchmark_service(
            Provider(),
            history_enabled=True,
        )
        operator_inferred = client.post(
            "/api/v1/evaluations/runs",
            headers=authorization(OPERATOR_TOKEN),
            json={"allow_external_provider_calls": True},
        )
        wildcard_missing = client.post(
            "/api/v1/evaluations/runs",
            headers=authorization(ADMIN_TOKEN),
            json={"allow_external_provider_calls": True},
        )
        wildcard_scoped = client.post(
            "/api/v1/evaluations/runs",
            headers=authorization(ADMIN_TOKEN),
            json={
                "history_namespace": "tenant-a",
                "allow_external_provider_calls": True,
            },
        )
        operator_foreign = client.post(
            "/api/v1/evaluations/runs",
            headers=authorization(OPERATOR_TOKEN),
            json={
                "history_namespace": "tenant-a",
                "allow_external_provider_calls": True,
            },
        )

    assert operator_inferred.status_code == 200
    assert wildcard_missing.status_code == 403
    assert wildcard_scoped.status_code == 200
    assert operator_foreign.status_code == 403


def test_persisted_dataset_roles_and_explicit_wildcard_namespace() -> None:
    definition = {
        "schema_version": 1,
        "name": "Authorization catalog set",
        "cases": [
            {
                "case_id": "case",
                "prompt": "Synthetic persisted authorization prompt",
                "expected_cache_hit": False,
            }
        ],
    }
    app = create_app(settings())
    repository = InMemoryEvaluationDatasetRepository()
    with TestClient(app) as client:
        app.state.benchmark_service = benchmark_service(
            Provider(),
            dataset_repository=repository,
        )
        viewer_list = client.get(
            "/api/v1/evaluations/datasets/persisted",
            headers=authorization(VIEWER_TOKEN),
        )
        viewer_create = client.post(
            "/api/v1/evaluations/datasets/persisted",
            headers=authorization(VIEWER_TOKEN),
            json={"dataset": definition},
        )
        operator_create = client.post(
            "/api/v1/evaluations/datasets/persisted",
            headers=authorization(OPERATOR_TOKEN),
            json={"dataset": definition},
        )
        dataset_id = operator_create.json()["dataset_id"]
        viewer_detail = client.get(
            f"/api/v1/evaluations/datasets/persisted/{dataset_id}",
            headers=authorization(VIEWER_TOKEN),
        )
        operator_delete = client.delete(
            f"/api/v1/evaluations/datasets/persisted/{dataset_id}",
            headers=authorization(OPERATOR_TOKEN),
        )
        wildcard_create_without_namespace = client.post(
            "/api/v1/evaluations/datasets/persisted",
            headers=authorization(ADMIN_TOKEN),
            json={"dataset": definition},
        )
        wildcard_create = client.post(
            "/api/v1/evaluations/datasets/persisted",
            headers=authorization(ADMIN_TOKEN),
            json={"namespace": "tenant-a", "dataset": definition},
        )
        wildcard_dataset_id = wildcard_create.json()["dataset_id"]
        wildcard_delete_without_namespace = client.delete(
            (f"/api/v1/evaluations/datasets/persisted/{wildcard_dataset_id}"),
            headers=authorization(ADMIN_TOKEN),
        )
        wildcard_delete = client.delete(
            (f"/api/v1/evaluations/datasets/persisted/{wildcard_dataset_id}"),
            params={"namespace": "tenant-a"},
            headers=authorization(ADMIN_TOKEN),
        )
        namespace_admin_delete = client.delete(
            f"/api/v1/evaluations/datasets/persisted/{dataset_id}",
            headers=authorization(NAMESPACE_ADMIN_TOKEN),
        )

    assert viewer_list.status_code == viewer_detail.status_code == 200
    assert viewer_create.status_code == operator_delete.status_code == 403
    assert operator_create.status_code == wildcard_create.status_code == 201
    assert wildcard_create_without_namespace.status_code == 403
    assert wildcard_delete_without_namespace.status_code == 403
    assert wildcard_delete.status_code == namespace_admin_delete.status_code == 200


def test_global_admin_can_update_the_threshold() -> None:
    with TestClient(create_app(settings())) as client:
        response = client.put(
            "/api/v1/cache/threshold",
            headers=authorization(ADMIN_TOKEN),
            json={"threshold": 0.9},
        )

    assert response.status_code == 200
    assert response.json() == {"threshold": 0.9}


def test_auth_session_returns_only_principal_metadata() -> None:
    with TestClient(create_app(settings())) as client:
        response = client.get(
            "/api/v1/auth/session",
            headers=authorization(VIEWER_TOKEN),
        )

    assert response.status_code == 200
    assert response.json() == {
        "name": "reader",
        "role": "viewer",
        "namespaces": ["default"],
    }
    assert VIEWER_TOKEN not in response.text


def test_entry_operations_do_not_reveal_foreign_namespace_existence() -> None:
    authorized_prompt = "authorized namespace entry"
    authorized_key = prompt_cache_key(authorized_prompt)
    foreign_prompt = "foreign namespace secret"
    foreign_key = prompt_cache_key(
        foreign_prompt,
        namespace="tenant-foreign",
    )
    missing_key = "0" * 64

    with TestClient(create_app(settings())) as client:
        authorized_created = client.post(
            "/api/v1/query",
            headers=authorization(ADMIN_TOKEN),
            json={"prompt": authorized_prompt},
        )
        created = client.post(
            "/api/v1/query",
            headers=authorization(ADMIN_TOKEN),
            json={
                "prompt": foreign_prompt,
                "namespace": "tenant-foreign",
            },
        )
        foreign_detail = client.get(
            f"/api/v1/cache/entries/{foreign_key}",
            headers=authorization(VIEWER_TOKEN),
        )
        missing_detail = client.get(
            f"/api/v1/cache/entries/{missing_key}",
            headers=authorization(VIEWER_TOKEN),
        )
        authorized_detail = client.get(
            f"/api/v1/cache/entries/{authorized_key}",
            headers=authorization(VIEWER_TOKEN),
        )
        viewer_delete = client.delete(
            f"/api/v1/cache/entries/{authorized_key}",
            headers=authorization(VIEWER_TOKEN),
        )
        foreign_delete = client.delete(
            f"/api/v1/cache/entries/{foreign_key}",
            headers=authorization(NAMESPACE_ADMIN_TOKEN),
        )
        missing_delete = client.delete(
            f"/api/v1/cache/entries/{missing_key}",
            headers=authorization(NAMESPACE_ADMIN_TOKEN),
        )
        global_detail = client.get(
            f"/api/v1/cache/entries/{foreign_key}",
            headers=authorization(ADMIN_TOKEN),
        )
        global_delete = client.delete(
            f"/api/v1/cache/entries/{foreign_key}",
            headers=authorization(ADMIN_TOKEN),
        )

    assert authorized_created.status_code == created.status_code == 200
    assert authorized_detail.status_code == 200
    assert authorized_detail.json()["cache_key"] == authorized_key
    assert "embedding" not in authorized_detail.json()
    assert viewer_delete.status_code == 403
    assert foreign_detail.status_code == missing_detail.status_code == 404
    assert foreign_detail.json() == missing_detail.json()
    assert foreign_delete.status_code == missing_delete.status_code == 404
    assert foreign_delete.json() == missing_delete.json()
    assert global_detail.status_code == 200
    assert global_detail.json()["namespace"] == "tenant-foreign"
    assert global_delete.status_code == 200
