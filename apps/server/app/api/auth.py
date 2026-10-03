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
    return AuthConfigResponse(
        authentication_required=request.app.state.settings.auth_mode == "token"
    )


@router.get("/session", response_model=AuthSessionResponse)
async def auth_session(
    request: Request,
) -> AuthSessionResponse:
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
