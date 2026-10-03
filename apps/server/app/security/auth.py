from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from typing import Annotated, cast

from fastapi import Depends, Request

from app.core.config import AuthRole, Settings
from app.core.exceptions import AuthenticationRequiredError, AuthorizationError

_ROLE_RANK: dict[AuthRole, int] = {
    "viewer": 0,
    "operator": 1,
    "admin": 2,
}


@dataclass(frozen=True, slots=True)
class Principal:
    name: str
    role: AuthRole
    namespaces: frozenset[str]

    @property
    def has_global_namespace_access(self) -> bool:
        return "*" in self.namespaces


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token.strip():
        raise AuthenticationRequiredError
    return token.strip()


def _principal_for_token(settings: Settings, token: str) -> Principal:
    presented_hash = sha256(token.encode("utf-8")).hexdigest()
    for configured in settings.auth_principals:
        if compare_digest(presented_hash, configured.token_sha256):
            return Principal(
                name=configured.name,
                role=configured.role,
                namespaces=frozenset(configured.namespaces),
            )
    raise AuthenticationRequiredError


def authenticate(request: Request) -> Principal:
    settings = _settings(request)
    if settings.auth_mode == "disabled":
        return Principal(
            name="local-development",
            role="admin",
            namespaces=frozenset({"*"}),
        )

    return _principal_for_token(settings, _bearer_token(request))


PrincipalDependency = Annotated[Principal, Depends(authenticate)]


def require_role(required: AuthRole) -> Callable[[Principal], Principal]:
    def dependency(principal: PrincipalDependency) -> Principal:
        if _ROLE_RANK[principal.role] < _ROLE_RANK[required]:
            raise AuthorizationError
        return principal

    return dependency


ViewerPrincipal = Annotated[Principal, Depends(require_role("viewer"))]
OperatorPrincipal = Annotated[Principal, Depends(require_role("operator"))]
AdminPrincipal = Annotated[Principal, Depends(require_role("admin"))]


def resolve_namespace(
    principal: Principal,
    requested: str | None,
    *,
    allow_global: bool,
) -> str | None:
    if requested == "*":
        raise AuthorizationError

    if principal.has_global_namespace_access:
        if requested is None and not allow_global:
            raise AuthorizationError
        return requested

    if requested is not None:
        if requested not in principal.namespaces:
            raise AuthorizationError
        return requested

    if len(principal.namespaces) == 1:
        return next(iter(principal.namespaces))
    raise AuthorizationError


def require_global_admin(principal: AdminPrincipal) -> Principal:
    if not principal.has_global_namespace_access:
        raise AuthorizationError
    return principal


GlobalAdminPrincipal = Annotated[Principal, Depends(require_global_admin)]
