"""Immutable validated models. Payload fields are deliberately absent from repr."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Self, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from ._semantics import (
    SemanticValidationError,
    cache_key_value,
    canonical_prompt,
    finite_number,
    namespace_value,
    normalized_vector,
    prompt_cache_key,
    valid_response,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _score(value: object) -> float:
    return finite_number(value, minimum=-1.0, maximum=1.0)


def _threshold(value: object) -> float:
    return finite_number(value, minimum=0.0, maximum=1.0)


def _nonnegative(value: object) -> float:
    return finite_number(value, minimum=0.0, maximum=float("inf"))


def _embedding(value: object) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        raise SemanticValidationError("Embedding must be a tuple or list")
    # Validation checks magnitude but preserves values; normalization belongs to use.
    components = cast("Sequence[float]", value)
    normalized_vector(components, dimensions=len(components))
    return tuple(float(component) for component in components)


Prompt = Annotated[str, BeforeValidator(canonical_prompt)]
Response = Annotated[str, BeforeValidator(valid_response)]
Namespace = Annotated[str, BeforeValidator(namespace_value)]
CacheKey = Annotated[str, BeforeValidator(cache_key_value)]
Timestamp = Annotated[datetime, AfterValidator(_utc)]
Score = Annotated[float, BeforeValidator(_score)]
Threshold = Annotated[float, BeforeValidator(_threshold)]
Nonnegative = Annotated[float, BeforeValidator(_nonnegative)]


class _Model(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", strict=True, hide_input_in_errors=True
    )


class EmbeddingSpace(_Model):
    """Immutable validated identity and dimensionality for compatible vectors.

    Identity should distinguish model/revision, preprocessing and pooling. Equal
    dimensions alone do not imply compatibility; the facade requires exact space
    equality and rejects changed metadata. This model describes a space without
    checking a provider's behavior or authenticating callers.
    """

    identity: str = Field(min_length=1, repr=False)
    dimensions: int = Field(gt=0)

    @model_validator(mode="after")
    def _identity(self) -> Self:
        if not self.identity.strip():
            raise ValueError("Embedding identity must be nonempty")
        return self


class CacheEntry(_Model):
    """Immutable validated payload at the store boundary.

    The key must match the canonical prompt and namespace. Embeddings become
    immutable finite, nonzero tuples; dimension compatibility is checked by the
    facade/store, and model validation alone does not normalize vector values.
    created_at is timezone-aware UTC and serves as the revision token in returned
    candidates; a store may advance it on write to prevent stale confirmation.
    Payloads omitted from repr remain present in normal serialization.
    """

    cache_key: CacheKey
    namespace: Namespace
    prompt: Prompt = Field(repr=False)
    response: Response = Field(repr=False)
    embedding: Annotated[tuple[float, ...], BeforeValidator(_embedding)] = Field(
        repr=False
    )
    created_at: Timestamp

    @model_validator(mode="after")
    def _key(self) -> Self:
        if self.cache_key != prompt_cache_key(self.prompt, namespace=self.namespace):
            raise ValueError("Cache key does not match canonical prompt and namespace")
        return self


class CacheMatch(_Model):
    """Detached nearest-candidate evidence, not a confirmed cache hit.

    similarity_score is a finite cosine score in [-1, 1]; it need not meet a facade
    threshold. The entry revision must still pass atomic store confirmation, since
    expiry, replacement or deletion can intervene. expires_at is UTC retention
    metadata, or None; the store's own clock determines authoritative expiry.
    """

    entry: CacheEntry = Field(repr=False)
    similarity_score: Score
    expires_at: Timestamp | None


class CacheHit(_Model):
    """Immutable confirmed-hit evidence returned by the facade.

    The validated score meets the inclusive similarity_threshold. Match fields
    identify the reused prompt/key/revision; age is nonnegative, and expires_at is
    optional UTC retention metadata. Constructing this model performs no lookup or
    confirmation and does not authorize the namespace or renew the entry's TTL.
    """

    response: Response = Field(repr=False)
    similarity_score: Score
    similarity_threshold: Threshold
    matched_prompt: Prompt = Field(repr=False)
    matched_cache_key: CacheKey
    cache_entry_created_at: Timestamp
    cache_entry_age_seconds: Nonnegative
    expires_at: Timestamp | None

    @model_validator(mode="after")
    def _eligible(self) -> Self:
        if self.similarity_score < self.similarity_threshold:
            raise ValueError("Hit score must meet threshold")
        return self


class CacheResult(_Model):
    """Immutable response and per-caller evidence from resolve.

    A hit requires complete match evidence and skips generation. cache_written
    stays False even if confirmation updates hit/access metadata. A miss may
    retain a candidate score below threshold or after failed confirmation;
    matched fields stay None. provider_called records invocation of the
    application generation callable, not necessarily external network work.
    cache_written records a completed policy-permitted entry write, not durability
    or future retention. Validation checks evidence consistency, not storage state.
    """

    response: Response = Field(repr=False)
    cache_hit: bool
    similarity_score: Score | None
    similarity_threshold: Threshold
    matched_prompt: Prompt | None = Field(repr=False)
    matched_cache_key: CacheKey | None
    cache_entry_created_at: Timestamp | None
    cache_entry_age_seconds: Nonnegative | None
    generation_skipped: bool
    provider_called: bool
    latency_ms: Nonnegative
    cache_written: bool

    @model_validator(mode="after")
    def _evidence(self) -> Self:
        matched = (
            self.matched_prompt,
            self.matched_cache_key,
            self.cache_entry_created_at,
            self.cache_entry_age_seconds,
        )
        if self.cache_hit:
            if self.similarity_score is None or any(value is None for value in matched):
                raise ValueError("Hit requires complete match evidence")
            if (
                self.similarity_score < self.similarity_threshold
                or self.provider_called
                or not self.generation_skipped
                or self.cache_written
            ):
                raise ValueError("Hit evidence is inconsistent")
        elif (
            any(value is not None for value in matched)
            or not self.provider_called
            or self.generation_skipped
        ):
            raise ValueError("Miss evidence is inconsistent")
        return self
