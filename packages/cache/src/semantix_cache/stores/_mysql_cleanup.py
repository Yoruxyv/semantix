"""Stable qualified definition of the public MySQL cleanup diagnostic type."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class MySQLCleanupStatus:
    """Safe process-local diagnostic; contains no connection or configuration.

    loop_closed is current for retained owners, captured at retirement for history.
    """

    cleanup_id: str
    state: Literal["pending", "retained", "retired", "escalation-required"]
    resources: tuple[str, ...]
    failure: str | None
    loop_closed: bool
