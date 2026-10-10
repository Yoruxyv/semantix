"""Validate interactive query policy and response evidence at the HTTP boundary.

QueryRequest replaces control characters and repeated whitespace, then checks
prompt bounds; this is text cleanup, not generation or a content-security
guarantee. Matching may normalize text separately; generation receives the
sanitized request prompt. Its namespace defaults to ``default`` and is authorized
by the router. Disabling cache or setting private disables both reads and writes;
otherwise read/write flags independently permit read-only or refresh behavior.
A non-null TTL must be a bounded integer under a write-permitted policy;
null or omission leaves default-TTL resolution to the service.

QueryResponse requires a hit score meeting the threshold and complete matched
entry metadata only for hits. Misses may carry a candidate score without a
confirmed hit. A coalesced follower can skip generation while remaining a miss;
generation_skipped alone is not hit evidence. Entry creation times are aware.
"""

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from app.api.schemas import StrictModel
from app.cache.domain.namespaces import DEFAULT_CACHE_NAMESPACE, CacheNamespace
from app.core.limits import (
    MAX_PROMPT_LENGTH,
    MAX_REQUEST_CACHE_TTL_SECONDS,
    MAX_RESPONSE_LENGTH,
)
from app.query.domain.policies import QueryCachePolicy
from semantix_cache._semantics import sanitize_prompt


class QueryRequest(StrictModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    namespace: CacheNamespace = DEFAULT_CACHE_NAMESPACE
    cache_enabled: bool = True
    cache_read_enabled: bool = True
    cache_write_enabled: bool = True
    private: bool = False
    cache_ttl_seconds: int | None = Field(
        default=None,
        ge=1,
        le=MAX_REQUEST_CACHE_TTL_SECONDS,
        strict=True,
    )

    @field_validator("prompt", mode="before")
    @classmethod
    def sanitize_prompt(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return sanitize_prompt(value)

    @model_validator(mode="after")
    def validate_cache_ttl_policy(self) -> "QueryRequest":
        """Reject TTL overrides when the effective request policy cannot write.

        Returns:
            The validated request, including an unchanged optional TTL.

        Raises:
            ValueError: A non-null TTL accompanies private, disabled or non-writing
                cache policy.
        """
        cache_write_allowed = (
            self.cache_enabled and self.cache_write_enabled and not self.private
        )
        if self.cache_ttl_seconds is not None and not cache_write_allowed:
            raise ValueError(
                "cache_ttl_seconds requires a cache policy that permits writes"
            )
        return self

    @property
    def cache_policy(self) -> QueryCachePolicy:
        """Translate request flags into independent cache read/write permissions.

        Returns:
            Policy carrying the request namespace and TTL. The router still must
            authorize that namespace before the application service uses it.
        """
        cache_allowed = self.cache_enabled and not self.private
        return QueryCachePolicy(
            namespace=self.namespace,
            read_enabled=cache_allowed and self.cache_read_enabled,
            write_enabled=cache_allowed and self.cache_write_enabled,
            cache_ttl_seconds=self.cache_ttl_seconds,
        )


class QueryResponse(StrictModel):
    response: str = Field(min_length=1, max_length=MAX_RESPONSE_LENGTH)
    cache_hit: bool
    similarity_score: float | None = Field(ge=-1, le=1)
    similarity_threshold: float = Field(ge=0, le=1)
    matched_prompt: str | None = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    matched_cache_key: str | None = Field(pattern=r"^[a-f0-9]{64}$")
    cache_entry_created_at: datetime | None
    cache_entry_age_seconds: float | None = Field(ge=0)
    generation_skipped: bool
    provider_called: bool
    latency_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_explainability(self) -> "QueryResponse":
        """Keep hit identity, threshold evidence and generation flags consistent.

        Returns:
            Response with matched-entry fields only for a hit. On misses, exactly
            one of provider_called and generation_skipped is true; a waiting
            coalesced follower uses the latter without becoming a cache hit.

        Raises:
            ValueError: Hit evidence is incomplete/below threshold, a miss includes
                matched identity, or generation flags contradict the decision.
        """
        matched_fields = (
            self.matched_prompt,
            self.matched_cache_key,
            self.cache_entry_created_at,
            self.cache_entry_age_seconds,
        )

        if self.cache_hit:
            if self.similarity_score is None or any(
                value is None for value in matched_fields
            ):
                raise ValueError(
                    "A cache hit must include its score and matched-entry metadata"
                )
            if self.similarity_score < self.similarity_threshold:
                raise ValueError("A cache-hit score must meet the request threshold")
            if not self.generation_skipped or self.provider_called:
                raise ValueError(
                    "A cache hit must skip generation and not call the provider"
                )
        else:
            if any(value is not None for value in matched_fields):
                raise ValueError("A cache miss cannot include matched-entry metadata")
            if self.generation_skipped == self.provider_called:
                raise ValueError(
                    "A cache miss must either call the provider or await generation"
                )

        return self

    @field_validator("cache_entry_created_at")
    @classmethod
    def require_cache_entry_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("cache_entry_created_at must be timezone-aware")
        return value
