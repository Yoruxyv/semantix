from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Literal, TypeAlias

import httpx
from pydantic import SecretStr

from app.providers.configuration import ProviderName, validate_provider_name
from app.providers.protocols import EmbeddingProvider, GenerationProvider

ProviderCapability = Literal["embedding", "generation"]
ProviderInstance: TypeAlias = EmbeddingProvider | GenerationProvider
SafeMetadataValue: TypeAlias = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class ProviderBuildContext:
    client: httpx.AsyncClient
    provider_timeout_seconds: float
    provider_max_response_bytes: int


ProviderBuilder: TypeAlias = Callable[[ProviderBuildContext], ProviderInstance]


@dataclass(frozen=True, slots=True)
class EmbeddingMetadata:
    dimensions: int
    space: str

    def __post_init__(self) -> None:
        if self.dimensions < 1:
            raise ValueError("Embedding dimensions must be greater than zero")
        if not self.space.strip():
            raise ValueError("Embedding space identity must not be empty")


EmbeddingMetadataResolver: TypeAlias = Callable[[], EmbeddingMetadata]
GenerationMetadata: TypeAlias = Mapping[str, SafeMetadataValue]
GenerationMetadataResolver: TypeAlias = Callable[[], GenerationMetadata]


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    name: ProviderName
    capabilities: frozenset[ProviderCapability]
    builder: ProviderBuilder
    embedding_metadata: EmbeddingMetadata | EmbeddingMetadataResolver | None = None
    generation_metadata: GenerationMetadata | GenerationMetadataResolver | None = None
    secrets: tuple[SecretStr, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", validate_provider_name(self.name))
        if not self.capabilities:
            raise ValueError("Provider registration must declare a capability")
        if not self.capabilities <= {"embedding", "generation"}:
            raise ValueError("Provider registration contains an invalid capability")
        if "embedding" in self.capabilities and self.embedding_metadata is None:
            raise ValueError("Embedding-capable providers require embedding metadata")
        if "embedding" not in self.capabilities and self.embedding_metadata is not None:
            raise ValueError("Embedding metadata requires the embedding capability")
        if "generation" in self.capabilities and self.generation_metadata is None:
            raise ValueError("Generation-capable providers require generation metadata")
        if (
            "generation" not in self.capabilities
            and self.generation_metadata is not None
        ):
            raise ValueError("Generation metadata requires the generation capability")

    def resolve_embedding_metadata(self) -> EmbeddingMetadata:
        value = self.embedding_metadata
        if value is None:
            raise ValueError(f"Provider {self.name!r} does not support embedding")
        resolved = value() if callable(value) else value
        if not isinstance(resolved, EmbeddingMetadata):
            raise ValueError("Embedding metadata resolver returned an invalid value")
        self._reject_secret_metadata((resolved.space,))
        return resolved

    def resolve_generation_metadata(self) -> GenerationMetadata:
        value = self.generation_metadata
        if value is None:
            raise ValueError(f"Provider {self.name!r} does not support generation")
        resolved = value() if callable(value) else value
        metadata = dict(resolved)
        if not metadata:
            raise ValueError("Generation metadata must not be empty")
        if any(
            not isinstance(key, str)
            or not key
            or not isinstance(item, (str, int, float, bool, type(None)))
            or (isinstance(item, float) and not isfinite(item))
            for key, item in metadata.items()
        ):
            raise ValueError("Generation metadata must contain stable scalar values")
        self._reject_secret_metadata(
            tuple(item for item in metadata.values() if isinstance(item, str))
        )
        return MappingProxyType(metadata)

    def configured_secrets(self) -> tuple[str, ...]:
        return tuple(
            value for secret in self.secrets if (value := secret.get_secret_value())
        )

    def _reject_secret_metadata(self, values: tuple[str, ...]) -> None:
        if any(
            secret in value for secret in self.configured_secrets() for value in values
        ):
            raise ValueError("Provider metadata must not contain registered secrets")


@dataclass(frozen=True, slots=True)
class ResolvedProviderSelection:
    embedding: ProviderRegistration
    generation: ProviderRegistration
    embedding_metadata: EmbeddingMetadata
    generation_metadata: GenerationMetadata

    @property
    def embedding_name(self) -> ProviderName:
        return self.embedding.name

    @property
    def generation_name(self) -> ProviderName:
        return self.generation.name


class ProviderRegistry:
    def __init__(self) -> None:
        self._registrations: dict[ProviderName, ProviderRegistration] = {}
        self._frozen = False

    @property
    def frozen(self) -> bool:
        return self._frozen

    def register(self, registration: ProviderRegistration) -> None:
        if self._frozen:
            raise RuntimeError("Provider registry is frozen")
        if registration.name in self._registrations:
            raise ValueError(f"Provider {registration.name!r} is already registered")
        self._registrations[registration.name] = registration

    def freeze(self) -> None:
        self._frozen = True

    def resolve(
        self,
        embedding_name: ProviderName,
        generation_name: ProviderName,
    ) -> ResolvedProviderSelection:
        self.freeze()
        embedding = self._resolve_capability(embedding_name, "embedding")
        generation = self._resolve_capability(generation_name, "generation")
        return ResolvedProviderSelection(
            embedding=embedding,
            generation=generation,
            embedding_metadata=embedding.resolve_embedding_metadata(),
            generation_metadata=generation.resolve_generation_metadata(),
        )

    def configured_secrets(self) -> tuple[str, ...]:
        return tuple(
            secret
            for registration in self._registrations.values()
            for secret in registration.configured_secrets()
        )

    def names(self) -> frozenset[ProviderName]:
        return frozenset(self._registrations)

    def _resolve_capability(
        self,
        name: ProviderName,
        capability: ProviderCapability,
    ) -> ProviderRegistration:
        try:
            registration = self._registrations[name]
        except KeyError as exc:
            raise ValueError(f"Provider {name!r} is not registered") from exc
        if capability not in registration.capabilities:
            raise ValueError(f"Provider {name!r} does not support {capability}")
        return registration
