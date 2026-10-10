"""Expose authentication policy and verify the current bearer identity.

These endpoints do not consume ordinary route quotas. Only token-mode
session verification records progressive failures, using the trusted client
address and configured local or PostgreSQL authority. Verification returns
principal metadata; it does not issue tokens, cookies or a server session.
"""

from fastapi import APIRouter, Request

from app.api.schemas import AuthConfigResponse, AuthSessionResponse
from app.core.exceptions import (
    AuthenticationRequiredError,
    AuthenticationTemporarilyLockedError,
)
from app.infrastructure.coordination import PostgresCoordination
from app.middleware.client_address import client_address
from app.security.auth import authenticate
from app.security.auth_attempts import AuthenticationAttemptTracker

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.get("/config", response_model=AuthConfigResponse)
async def auth_config(request: Request) -> AuthConfigResponse:
    """Expose whether authentication is required, without principal details."""
    return AuthConfigResponse(
        authentication_required=request.app.state.settings.auth_mode == "token"
    )


@router.get("/session", response_model=AuthSessionResponse)
async def auth_session(
    request: Request,
) -> AuthSessionResponse:
    """Verify credentials and return permitted identity metadata.

    Disabled mode bypasses lockout tracking. In token mode, an active lock
    rejects even valid credentials; successful verification after expiry resets
    escalation. Failures on other protected endpoints do not count here.
    PostgreSQL coordination failures propagate without a local fallback.

    Args:
        request: Request supplying credentials, trusted address and app state.

    Returns:
        Principal name, role and sorted authorized namespaces, without the
        original token or configured digest.

    Raises:
        AuthenticationRequiredError: Credentials fail before lockout applies.
        AuthenticationTemporarilyLockedError: Lockout applies, producing HTTP
            429 with Retry-After.
        CoordinationStorageError: The shared authority reports a storage
            failure, producing HTTP 503.
    """
    settings = request.app.state.settings
    if settings.auth_mode == "disabled":
        principal = authenticate(request)
        return AuthSessionResponse(
            name=principal.name,
            role=principal.role,
            namespaces=sorted(principal.namespaces),
        )

    address = client_address(request)
    if settings.coordination_backend == "postgres":
        coordinator: PostgresCoordination = request.app.state.coordination
        try:
            principal = authenticate(request)
        except AuthenticationRequiredError:
            retry_after = await coordinator.record_session_attempt(
                address, succeeded=False
            )
            if retry_after is not None:
                raise AuthenticationTemporarilyLockedError(retry_after) from None
            raise
        retry_after = await coordinator.record_session_attempt(address, succeeded=True)
        if retry_after is not None:
            raise AuthenticationTemporarilyLockedError(retry_after)
    else:
        tracker: AuthenticationAttemptTracker = (
            request.app.state.authentication_attempt_tracker
        )
        retry_after = tracker.retry_after(address)
        if retry_after is not None:
            raise AuthenticationTemporarilyLockedError(retry_after)

        try:
            principal = authenticate(request)
        except AuthenticationRequiredError:
            retry_after = tracker.record_failure(address)
            if retry_after is not None:
                raise AuthenticationTemporarilyLockedError(retry_after) from None
            raise
        tracker.reset(address)

    return AuthSessionResponse(
        name=principal.name,
        role=principal.role,
        namespaces=sorted(principal.namespaces),
    )
