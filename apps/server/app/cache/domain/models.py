import math
from datetime import datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.cache.domain.namespaces import CacheNamespace
from app.core.limits import (
    MAX_PROMPT_LENGTH,
    MAX_RESPONSE_LENGTH,
)


class CacheModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CacheEntry(CacheModel):
    cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    namespace: CacheNamespace
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    response: str = Field(min_length=1, max_length=MAX_RESPONSE_LENGTH)
    embedding: list[float] = Field(min_length=1)
    created_at: datetime

    @field_validator("embedding")
    @classmethod
    def validate_embedding(cls, value: list[float]) -> list[float]:
        if not all(math.isfinite(component) for component in value):
            raise ValueError("Embedding components must be finite")
        return value

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class CacheCandidate(CacheModel):
    entry: CacheEntry
    similarity_score: float = Field(ge=-1, le=1)


class CacheLookupResult(CacheModel):
    cache_hit: bool
    response: str | None = Field(default=None, max_length=MAX_RESPONSE_LENGTH)
    similarity_score: float | None = Field(default=None, ge=-1, le=1)
    similarity_threshold: float = Field(ge=0, le=1)
    matched_prompt: str | None = Field(
        default=None, min_length=1, max_length=MAX_PROMPT_LENGTH
    )
    matched_cache_key: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    cache_entry_created_at: datetime | None = None
    embedding: list[float] = Field(min_length=1)

    @field_validator("embedding")
    @classmethod
    def validate_embedding(cls, value: list[float]) -> list[float]:
        if not all(math.isfinite(component) for component in value):
            raise ValueError("Embedding components must be finite")
        return value

    @model_validator(mode="after")
    def validate_lookup(self) -> "CacheLookupResult":
        matched_fields = (
            self.matched_prompt,
            self.matched_cache_key,
            self.cache_entry_created_at,
        )

        if self.cache_hit and (
            self.response is None
            or self.similarity_score is None
            or any(value is None for value in matched_fields)
        ):
            raise ValueError(
                "A cache hit must include a response, score, and matched-entry metadata"
            )
        if (
            self.cache_hit
            and self.similarity_score is not None
            and self.similarity_score < self.similarity_threshold
        ):
            raise ValueError("A cache-hit score must meet the lookup threshold")
        if not self.cache_hit and (
            self.response is not None
            or any(value is not None for value in matched_fields)
        ):
            raise ValueError(
                "A cache miss cannot include a response or matched-entry metadata"
            )

        return self

    @field_validator("cache_entry_created_at")
    @classmethod
    def require_cache_entry_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("cache_entry_created_at must be timezone-aware")
        return value
