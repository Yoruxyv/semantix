import asyncio
from hashlib import sha256

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.factory import create_app
from tests.benchmark.api.test_history_routes import service
from tests.benchmark.history_support import (
    InMemoryEvaluationRunHistoryRepository,
    make_history_record,
)

VIEWER_TOKEN = "history-viewer-secret"
SCOPED_ADMIN_TOKEN = "history-admin-secret"
GLOBAL_ADMIN_TOKEN = "history-global-admin-secret"


def _token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def _settings() -> Settings:
    return Settings(
        embedding_provider="mock",
        generation_provider="mock",
        hf_api_key=None,
        cache_backend="memory",
        allowed_origins=["http://localhost:5173"],
        auth_mode="token",
        auth_principals=[
            {
                "name": "history-viewer",
                "token_sha256": _token_hash(VIEWER_TOKEN),
                "role": "viewer",
                "namespaces": ["tenant-a"],
            },
            {
                "name": "history-admin",
                "token_sha256": _token_hash(SCOPED_ADMIN_TOKEN),
                "role": "admin",
                "namespaces": ["tenant-a"],
            },
            {
                "name": "history-global-admin",
                "token_sha256": _token_hash(GLOBAL_ADMIN_TOKEN),
                "role": "admin",
                "namespaces": ["*"],
            },
        ],
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _repository() -> tuple[
    InMemoryEvaluationRunHistoryRepository,
    str,
    str,
]:
    repository = InMemoryEvaluationRunHistoryRepository()
    owned = make_history_record(
        run_id=f"{1:032x}",
        namespace="tenant-a",
    )
    foreign = make_history_record(
        run_id=f"{2:032x}",
        namespace="tenant-b",
    )
    asyncio.run(repository.persist_terminal_run(owned))
    asyncio.run(repository.persist_terminal_run(foreign))
    return repository, owned.context.run_id, foreign.context.run_id


def test_scoped_viewer_cannot_distinguish_foreign_history_from_missing_history() -> (
    None
):
    repository, owned_id, foreign_id = _repository()
    missing_id = f"{3:032x}"
    app = create_app(_settings())

    with TestClient(app) as client:
        app.state.benchmark_service = service(repository)
        owned = client.get(
            f"/api/v1/evaluations/runs/{owned_id}",
            headers=_headers(VIEWER_TOKEN),
        )
        foreign = client.get(
            f"/api/v1/evaluations/runs/{foreign_id}",
            headers=_headers(VIEWER_TOKEN),
        )
        missing = client.get(
            f"/api/v1/evaluations/runs/{missing_id}",
            headers=_headers(VIEWER_TOKEN),
        )
        foreign_list = client.get(
            "/api/v1/evaluations/runs",
            params={"namespace": "tenant-b"},
            headers=_headers(VIEWER_TOKEN),
        )

    assert owned.status_code == 200
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert foreign.json()["error"] == "evaluation_run_history_not_found"
    assert foreign_list.status_code == 403
    assert foreign_list.json()["error"] == "forbidden"


def test_scoped_admin_delete_does_not_disclose_foreign_history() -> None:
    repository, owned_id, foreign_id = _repository()
    missing_id = f"{3:032x}"
    app = create_app(_settings())

    with TestClient(app) as client:
        app.state.benchmark_service = service(repository)
        foreign = client.delete(
            f"/api/v1/evaluations/runs/{foreign_id}",
            headers=_headers(SCOPED_ADMIN_TOKEN),
        )
        missing = client.delete(
            f"/api/v1/evaluations/runs/{missing_id}",
            headers=_headers(SCOPED_ADMIN_TOKEN),
        )
        owned = client.delete(
            f"/api/v1/evaluations/runs/{owned_id}",
            headers=_headers(SCOPED_ADMIN_TOKEN),
        )

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert foreign.json()["error"] == "evaluation_run_history_not_found"
    assert owned.status_code == 200
    assert owned.json()["namespace"] == "tenant-a"


def test_history_api_never_accepts_global_marker_as_retained_ownership() -> None:
    repository, owned_id, _ = _repository()
    app = create_app(_settings())

    with TestClient(app) as client:
        app.state.benchmark_service = service(repository)
        run = client.post(
            "/api/v1/evaluations/runs",
            headers=_headers(GLOBAL_ADMIN_TOKEN),
            json={
                "history_namespace": "*",
                "allow_external_provider_calls": True,
            },
        )
        deleted = client.delete(
            f"/api/v1/evaluations/runs/{owned_id}",
            params={"namespace": "*"},
            headers=_headers(GLOBAL_ADMIN_TOKEN),
        )

    assert run.status_code == 422
    assert run.json()["error"] == "validation_error"
    assert deleted.status_code == 422
    assert deleted.json()["error"] == "validation_error"
