"""Enforce bearer identity, ordered roles and namespace access on the server.

Viewer dependencies admit reads; operator dependencies also admit queries
and evaluation work; admin dependencies admit destructive management.
Global threshold updates and process-wide observability require wildcard
admins. Feature routes select these dependencies and enforce resource scope.
A cache namespace is a storage boundary, not an authentication mechanism.
"""

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
    """Authenticated identity with independent role and namespace permissions.

    ``*`` grants global namespace access; it is not a concrete cache namespace.
    Settings permit this marker only for admins, alone in the namespace list.
    """

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
    """Resolve the request identity without recording session lockout attempts.

    Disabled authentication is intended for trusted local development and
    returns the implicit ``local-development`` admin with wildcard scope.
    Token mode hashes the original bearer token as UTF-8 SHA-256, compares the
    digest with configured digests, and returns the matching principal.

    Args:
        request: Request whose application state supplies validated settings.

    Returns:
        Authenticated identity and its role and namespace permissions.

    Raises:
        AuthenticationRequiredError: Bearer credentials are missing, malformed
            or do not match a configured principal in token mode.
    """
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
    """Build a dependency enforcing the viewer < operator < admin order.

    Args:
        required: Minimum role; this does not grant namespace access.

    Returns:
        Dependency authenticating the request and returning the principal,
        or raising AuthorizationError when its role is insufficient.
    """

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
    """Authorize a namespace before passing it to an application operation.

    Restricted principals may select only an allowed namespace. Omission is
    inferred only for a sole namespace. Wildcard principals may select any
    concrete namespace, or omit it for a global operation when permitted.

    Args:
        principal: Identity already authenticated by the route dependency.
        requested: Concrete namespace, or None for omitted selection. The
            permission marker ``*`` is always rejected as a requested value.
        allow_global: Whether a wildcard principal may omit the namespace to
            request global scope; does not broaden restricted permissions.

    Returns:
        Authorized concrete namespace, or None for permitted global scope.

    Raises:
        AuthorizationError: Selection is unauthorized, ambiguous, wildcard
            input, or a required concrete namespace is missing.
    """
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
    """Require wildcard namespace access after the admin role dependency.

    Args:
        principal: Identity whose admin role is enforced by AdminPrincipal
            during FastAPI dependency resolution.

    Returns:
        Principal allowed to administer process-wide or global state.

    Raises:
        AuthorizationError: The admin has only restricted namespace access.
    """
    if not principal.has_global_namespace_access:
        raise AuthorizationError
    return principal


GlobalAdminPrincipal = Annotated[Principal, Depends(require_global_admin)]
