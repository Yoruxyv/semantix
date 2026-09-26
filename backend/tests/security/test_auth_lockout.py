from dataclasses import dataclass
from hashlib import sha256

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from httpx import Response

from app.api.auth import auth_session
from app.core.config import Settings
from app.core.exceptions import (
    AuthenticationRequiredError,
    AuthenticationTemporarilyLockedError,
    CoordinationStorageError,
)
from app.factory import create_app

VALID_TOKEN = "valid-operator-token"
LOCKOUT_ERROR = {
    "error": "authentication_temporarily_locked",
    "detail": "Too many failed authentication attempts. Please try again later.",
}


@dataclass
class FakeClock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def token_settings(
    *,
    auth_mode: str = "token",
    rate_limit: str = "1000/minute",
) -> Settings:
    principals: list[dict[str, object]] = []
    if auth_mode == "token":
        principals = [
            {
                "name": "operator",
                "token_sha256": token_hash(VALID_TOKEN),
                "role": "admin",
                "namespaces": ["*"],
            }
        ]
    return Settings(
        embedding_provider="mock",
        generation_provider="mock",
        hf_api_key=None,
        cache_backend="memory",
        allowed_origins=["http://localhost:5173"],
        auth_mode=auth_mode,
        auth_principals=principals,
        rate_limit=rate_limit,
    )


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def invalid_attempt(
    client: TestClient,
    token: str = "wrong-token",
) -> Response:
    response: Response = client.get(
        "/api/v1/auth/session",
        headers=authorization(token),
    )
    return response


def trigger_lock(client: TestClient, expected_seconds: int) -> None:
    assert invalid_attempt(client).status_code == 401
    assert invalid_attempt(client).status_code == 401
    response = invalid_attempt(client)
    assert response.status_code == 429
    assert response.headers["retry-after"] == str(expected_seconds)
    assert response.json() == LOCKOUT_ERROR


def test_valid_sessions_do_not_consume_the_application_rate_limit() -> None:
    with TestClient(create_app(token_settings(rate_limit="1/minute"))) as client:
        sessions = [invalid_attempt(client, VALID_TOKEN) for _ in range(10)]
        first_limited = client.get(
            "/api/v1/cache/stats",
            headers=authorization(VALID_TOKEN),
        )
        second_limited = client.get(
            "/api/v1/cache/stats",
            headers=authorization(VALID_TOKEN),
        )

    assert all(response.status_code == 200 for response in sessions)
    assert all("rate_limit_exceeded" not in response.text for response in sessions)
    assert first_limited.status_code == 200
    assert second_limited.status_code == 429
    assert second_limited.json()["error"] == "rate_limit_exceeded"


def test_low_application_limit_does_not_replace_progressive_lockout() -> None:
    clock = FakeClock()
    with TestClient(
        create_app(
            token_settings(rate_limit="1/minute"),
            auth_attempt_clock=clock,
        )
    ) as client:
        trigger_lock(client, 30)


def test_lockout_progresses_only_after_three_new_failures_per_stage() -> None:
    clock = FakeClock()
    with TestClient(create_app(token_settings(), auth_attempt_clock=clock)) as client:
        trigger_lock(client, 30)

        clock.advance(10)
        during_lock = invalid_attempt(client, VALID_TOKEN)
        assert during_lock.status_code == 429
        assert during_lock.headers["retry-after"] == "20"

        clock.advance(20)
        assert invalid_attempt(client).status_code == 401
        assert invalid_attempt(client).status_code == 401
        second_lock = invalid_attempt(client)
        assert second_lock.status_code == 429
        assert second_lock.headers["retry-after"] == "60"

        clock.advance(60)
        trigger_lock(client, 3_600)

        clock.advance(3_600)
        trigger_lock(client, 3_600)


def test_requests_during_lock_do_not_extend_or_increment_it() -> None:
    clock = FakeClock()
    with TestClient(create_app(token_settings(), auth_attempt_clock=clock)) as client:
        trigger_lock(client, 30)
        clock.advance(5)

        first = invalid_attempt(client)
        second = invalid_attempt(client)

        assert first.headers["retry-after"] == "25"
        assert second.headers["retry-after"] == "25"

        clock.advance(25)
        assert invalid_attempt(client).status_code == 401
        assert invalid_attempt(client).status_code == 401
        escalated = invalid_attempt(client)
        assert escalated.status_code == 429
        assert escalated.headers["retry-after"] == "60"


def test_success_resets_failure_count_escalation_and_active_lock() -> None:
    clock = FakeClock()
    with TestClient(create_app(token_settings(), auth_attempt_clock=clock)) as client:
        trigger_lock(client, 30)
        clock.advance(30)
        trigger_lock(client, 60)
        clock.advance(60)

        successful = invalid_attempt(client, VALID_TOKEN)
        assert successful.status_code == 200
        assert successful.json()["name"] == "operator"

        trigger_lock(client, 30)


def test_clients_have_independent_attempt_state() -> None:
    clock = FakeClock()
    application = create_app(token_settings(), auth_attempt_clock=clock)
    with (
        TestClient(
            application,
            client=("198.51.100.10", 50_000),
        ) as first_client,
        TestClient(
            application,
            client=("198.51.100.11", 50_001),
        ) as second_client,
    ):
        trigger_lock(first_client, 30)

        assert invalid_attempt(second_client).status_code == 401
        assert invalid_attempt(second_client).status_code == 401
        second_lock = invalid_attempt(second_client)
        assert second_lock.status_code == 429
        assert second_lock.headers["retry-after"] == "30"


def test_missing_and_malformed_credentials_count_as_failures() -> None:
    clock = FakeClock()
    with TestClient(create_app(token_settings(), auth_attempt_clock=clock)) as client:
        missing = client.get("/api/v1/auth/session")
        malformed = client.get(
            "/api/v1/auth/session",
            headers={"Authorization": "Basic credentials"},
        )
        locked = client.get(
            "/api/v1/auth/session",
            headers={"Authorization": "Bearer "},
        )

    assert missing.status_code == 401
    assert malformed.status_code == 401
    assert locked.status_code == 429
    assert locked.headers["retry-after"] == "30"


def test_failures_on_other_protected_routes_do_not_count() -> None:
    clock = FakeClock()
    with TestClient(create_app(token_settings(), auth_attempt_clock=clock)) as client:
        for _ in range(5):
            protected = client.get(
                "/api/v1/cache/stats",
                headers=authorization("wrong-token"),
            )
            assert protected.status_code == 401

        assert invalid_attempt(client).status_code == 401
        assert invalid_attempt(client).status_code == 401
        locked = invalid_attempt(client)

    assert locked.status_code == 429
    assert locked.headers["retry-after"] == "30"


def test_disabled_authentication_bypasses_attempt_tracking() -> None:
    clock = FakeClock()
    application = create_app(
        token_settings(auth_mode="disabled", rate_limit="1/minute"),
        auth_attempt_clock=clock,
    )
    with TestClient(application) as client:
        for _ in range(5):
            response = invalid_attempt(client)
            assert response.status_code == 200
            assert response.json()["name"] == "local-development"

    assert (
        application.state.authentication_attempt_tracker.retry_after("testclient")
        is None
    )


def test_stale_escalation_state_is_pruned_after_inactivity() -> None:
    clock = FakeClock()
    with TestClient(create_app(token_settings(), auth_attempt_clock=clock)) as client:
        trigger_lock(client, 30)
        clock.advance(86_400)

        trigger_lock(client, 30)


def test_lockout_response_does_not_expose_authentication_secrets() -> None:
    clock = FakeClock()
    configured_hash = token_hash(VALID_TOKEN)
    with TestClient(create_app(token_settings(), auth_attempt_clock=clock)) as client:
        trigger_lock(client, 30)
        response = invalid_attempt(client, VALID_TOKEN)

    assert response.status_code == 429
    assert response.json() == LOCKOUT_ERROR
    assert VALID_TOKEN not in response.text
    assert configured_hash not in response.text
    assert "operator" not in response.text


@pytest.mark.asyncio
async def test_shared_session_lockout_never_falls_back_to_process_memory() -> None:
    class FakeCoordination:
        def __init__(self) -> None:
            self.locked = False
            self.unavailable = False
            self.attempts: list[bool] = []

        async def record_session_attempt(
            self, address: str, *, succeeded: bool
        ) -> int | None:
            assert address == "198.51.100.10"
            if self.unavailable:
                raise CoordinationStorageError
            self.attempts.append(succeeded)
            return 30 if self.locked else None

    application = create_app(
        token_settings().model_copy(update={"coordination_backend": "postgres"})
    )
    coordinator = FakeCoordination()
    application.state.coordination = coordinator

    def request(token: str) -> Request:
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/auth/session",
                "headers": [(b"authorization", f"Bearer {token}".encode())],
                "client": ("198.51.100.10", 50000),
                "app": application,
            }
        )

    with pytest.raises(AuthenticationRequiredError):
        await auth_session(request("invalid"))
    coordinator.locked = True
    with pytest.raises(AuthenticationTemporarilyLockedError):
        await auth_session(request(VALID_TOKEN))
    coordinator.unavailable = True
    with pytest.raises(CoordinationStorageError):
        await auth_session(request(VALID_TOKEN))
    assert coordinator.attempts == [False, True]
