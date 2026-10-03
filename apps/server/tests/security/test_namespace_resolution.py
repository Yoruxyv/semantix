import pytest

from app.core.exceptions import AuthorizationError
from app.security.auth import Principal, resolve_namespace


@pytest.mark.parametrize("allow_global", [False, True])
def test_global_authorization_marker_is_never_a_concrete_namespace(
    allow_global: bool,
) -> None:
    principal = Principal(
        name="global-admin",
        role="admin",
        namespaces=frozenset({"*"}),
    )

    with pytest.raises(AuthorizationError):
        resolve_namespace(principal, "*", allow_global=allow_global)


def test_global_scope_is_represented_only_by_an_omitted_namespace() -> None:
    principal = Principal(
        name="global-admin",
        role="admin",
        namespaces=frozenset({"*"}),
    )

    assert resolve_namespace(principal, None, allow_global=True) is None

    with pytest.raises(AuthorizationError):
        resolve_namespace(principal, None, allow_global=False)


def test_scoped_principal_infers_only_a_single_authorized_namespace() -> None:
    sole = Principal(
        name="sole-operator",
        role="operator",
        namespaces=frozenset({"tenant-a"}),
    )
    multiple = Principal(
        name="multi-operator",
        role="operator",
        namespaces=frozenset({"tenant-a", "tenant-b"}),
    )

    assert resolve_namespace(sole, None, allow_global=False) == "tenant-a"

    with pytest.raises(AuthorizationError):
        resolve_namespace(multiple, None, allow_global=False)

    assert resolve_namespace(multiple, "tenant-b", allow_global=False) == "tenant-b"
