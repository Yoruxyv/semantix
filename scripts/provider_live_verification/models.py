"""Tooling configuration and sanitized receipt validation; no runtime API exports."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Provider = Literal["openai", "gemini", "huggingface", "ollama", "anthropic"]


Result = Literal["PASS", "FAIL", "UNAVAILABLE"]


Status = Literal[
    "not_attempted",
    "success",
    "redirect",
    "client_error",
    "server_error",
    "transport_error",
    "timeout",
    "attempt_limit",
    "endpoint_rejected",
]


Failure = Literal[
    "none",
    "provider_error",
    "semantic_assertion",
    "deadline",
    "cleanup",
    "task_leak",
]


ModelName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")]


Counter = Annotated[int, Field(ge=0)]


DEFAULT_TIMEOUT = 60.0


class SafeInputError(Exception):
    """Static diagnostics only; never attach raw credential/input exceptions."""


class Options(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", strict=True, hide_input_in_errors=True
    )
    provider: Provider
    model: ModelName
    embedding_model: ModelName
    embedding_dimensions: int = Field(ge=1, le=16000)
    challenge: str | None = Field(default=None, pattern=r"^[ -~]{1,128}$")
    timeout: float = Field(default=DEFAULT_TIMEOUT, ge=10, le=120, allow_inf_nan=False)
    max_attempts: int = Field(ge=1, le=3)
    model_overridden: bool = False
    embedding_overridden: bool = False
    use_env: bool = False

    @model_validator(mode="after")
    def local_configuration(self) -> Self:
        if self.provider == "anthropic" and (
            self.embedding_model != "deterministic-local-v1"
            or self.embedding_dimensions != 2
            or self.max_attempts != 1
            or self.embedding_overridden
        ):
            raise ValueError(
                "Anthropic requires the deterministic local embedding mode"
            )
        return self


class Source(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    semantix_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    branch: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,159}$")
    source_dirty: bool


class Receipt(Source):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    challenge: str | None = Field(pattern=r"^[ -~]{1,128}$")
    provider: Provider
    api_source: Literal["first-party", "local-first-party"]
    adapter_path: str
    utc_timestamp: datetime
    python_version: str
    platform: str
    model: ModelName
    embedding_model: ModelName
    embedding_dimensions: int = Field(ge=1, le=16000)
    embedding_source: Literal["first-party", "deterministic-local"]
    model_overridden: bool
    embedding_overridden: bool
    max_http_attempts: int = Field(ge=1, le=3)
    total_timeout_seconds: float = Field(ge=10, le=120, allow_inf_nan=False)
    request_timeout_seconds: float = Field(gt=0, le=15, allow_inf_nan=False)
    http_attempts: Counter
    http_status_category: Status
    embedding_calls: Counter
    generation_calls: Counter
    cache_writes: Counter
    confirmed_hits: Counter
    first_resolve_miss: bool
    second_generation_skipped: bool
    response_equal: bool
    ownership_verified: bool
    retry_count: Literal[0]
    cleanup_status: Literal["complete", "failed"]
    remaining_async_tasks: Counter
    result: Result
    failure_category: Failure

    @model_validator(mode="after")
    def consistent(self) -> Self:
        local = self.provider == "anthropic"
        expected_attempts = 1 if local else 3
        if (
            self.utc_timestamp.tzinfo is None
            or self.utc_timestamp.utcoffset() != UTC.utcoffset(self.utc_timestamp)
            or self.adapter_path != f"semantix_cache.adapters.{self.provider}"
            or self.api_source
            != ("local-first-party" if self.provider == "ollama" else "first-party")
            or self.embedding_source
            != ("deterministic-local" if local else "first-party")
            or (
                local
                and (
                    self.embedding_model != "deterministic-local-v1"
                    or self.embedding_dimensions != 2
                    or self.embedding_overridden
                    or self.max_http_attempts != 1
                )
            )
            or self.http_attempts > self.max_http_attempts
            or (self.result == "UNAVAILABLE" and self.provider != "ollama")
        ):
            raise ValueError("Receipt metadata is inconsistent")
        if self.result == "PASS" and (
            (
                self.http_attempts,
                self.embedding_calls,
                self.generation_calls,
                self.cache_writes,
                self.confirmed_hits,
            )
            != (expected_attempts, 2, 1, 1, 1)
            or not all(
                (
                    self.first_resolve_miss,
                    self.second_generation_skipped,
                    self.response_equal,
                    self.ownership_verified,
                )
            )
            or self.http_status_category != "success"
            or self.cleanup_status != "complete"
            or self.remaining_async_tasks != 0
            or self.failure_category != "none"
        ):
            raise ValueError("PASS requires complete observed evidence")
        return self


def reject_secret_metadata(key: str, texts: Sequence[str]) -> None:
    if key and any(key in text or json.dumps(key)[1:-1] in text for text in texts):
        raise SafeInputError("Credential must not appear in receipt metadata")
