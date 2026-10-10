"""Explicit provider registration and metadata selection before construction.

Registration declares capabilities and deferred builders. Resolution freezes
the registry and evaluates selected metadata without constructing adapters;
``factory`` later invokes builders with application-owned transport. This
registry configures server providers, independently of embedded integrations.
"""

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
# Generation metadata accepts these scalars; resolution rejects nonfinite floats.
SafeMetadataValue: TypeAlias = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class ProviderBuildContext:
    """Borrowed HTTP client and configured limits supplied to a provider builder.

    Application lifespan owns ``client`` and closes it on exit, including failed
    startup. Adapters must not close it. The timeout and response-size fields are
    settings inputs; shared ``post_json`` takes its operation deadline from the
    supplied client's read timeout, rather than consulting this context field.
    Additional adapter resources require deployment-owned cleanup.
    """

    client: httpx.AsyncClient
    provider_timeout_seconds: float
    provider_max_response_bytes: int


# Synchronous construction callback; registration and metadata resolution do not run it.
ProviderBuilder: TypeAlias = Callable[[ProviderBuildContext], ProviderInstance]


@dataclass(frozen=True, slots=True)
class EmbeddingMetadata:
    """Vector dimensions and semantic space identity used to configure the cache.

    Construction rejects dimensions below one and a blank ``space``. Keep the
    identity stable for compatible vectors; change it when model or preprocessing
    changes make stored vectors incompatible. Validation checks presence, not
    semantic compatibility. Secret checks occur during registration resolution.
    """

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
    """One named provider's declared capabilities, builder and metadata sources.

    Construction validates the name, nonempty supported capabilities and the
    presence of metadata for exactly those capabilities. It invokes neither
    the builder nor callable metadata sources. Metadata resolvers run when
    selected and should describe stable configuration without provider calls.

    ``secrets`` supplies known credentials for server logging redaction. Each
    resolution rejects this registration's nonempty secret strings appearing
    as substrings in embedding ``space`` or string generation metadata values.
    Keys and other output are not covered; this is not universal redaction.
    """

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
        """Evaluate embedding metadata and check its type and registered secrets.

        Exceptions raised by a custom resolver propagate unchanged.

        Returns:
            The supplied or resolved ``EmbeddingMetadata``, without construction
            of a provider or caching of a callable result.

        Raises:
            ValueError: Embedding metadata is absent or its space contains a
                nonempty secret registered on this provider.
            TypeError: A resolver returns something other than ``EmbeddingMetadata``.
        """
        value = self.embedding_metadata
        if value is None:
            raise ValueError(f"Provider {self.name!r} does not support embedding")
        resolved = value() if callable(value) else value
        if not isinstance(resolved, EmbeddingMetadata):
            raise TypeError("Embedding metadata resolver returned an invalid value")
        self._reject_secret_metadata((resolved.space,))
        return resolved

    def resolve_generation_metadata(self) -> GenerationMetadata:
        """Evaluate, validate and copy generation configuration for selection.

        Metadata must be nonempty, with nonempty string keys and values limited
        to strings, integers, finite floats, booleans or ``None``. String values
        must not contain this registration's nonempty secrets. Use stable values:
        server benchmark configuration derives its fingerprint from this mapping.

        Invalid mapping results and custom resolver exceptions propagate.

        Returns:
            A read-only copy of the resolved mapping. Callable results are not
            cached between resolutions.

        Raises:
            ValueError: Metadata is absent, empty, violates scalar/key constraints
                or contains a registered secret in a string value.
        """
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
        """Return nonempty credential values for the server's redaction setup."""
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
    """Selected registrations and resolved metadata passed into adapter construction.

    This contains configuration, not provider instances. The factory uses the
    selected names and metadata for its bundle; metadata resolvers are not run
    again when this selection is supplied. Both capabilities may refer to the
    same registration.
    """

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
    """Explicit name-to-registration catalog frozen by selection.

    Add providers before ``resolve`` or ``freeze``. Freezing prevents further
    registration even if selection fails. Later calls to ``resolve`` remain
    allowed; mutable state captured by builders and resolvers is not frozen.
    Builders execute only in the factory's construction phase.
    """

    def __init__(self) -> None:
        self._registrations: dict[ProviderName, ProviderRegistration] = {}
        self._frozen = False

    @property
    def frozen(self) -> bool:
        return self._frozen

    def register(self, registration: ProviderRegistration) -> None:
        """Add a registration without invoking its builder or metadata resolvers.

        Args:
            registration: Provider whose name and capability declarations have
                already been validated by ``ProviderRegistration``.

        Raises:
            RuntimeError: The registry is frozen.
            ValueError: The provider name is already registered.
        """
        if self._frozen:
            raise RuntimeError("Provider registry is frozen")
        if registration.name in self._registrations:
            raise ValueError(f"Provider {registration.name!r} is already registered")
        self._registrations[registration.name] = registration

    def freeze(self) -> None:
        """Prevent further registration; repeated calls have no additional effect."""
        self._frozen = True

    def resolve(
        self,
        embedding_name: ProviderName,
        generation_name: ProviderName,
    ) -> ResolvedProviderSelection:
        """Freeze registration, check capabilities and evaluate selected metadata.

        Freezing happens before lookup and remains in effect on failure. Each call
        resolves metadata afresh; it never invokes provider builders.

        Other metadata resolver or mapping conversion errors propagate unchanged.

        Args:
            embedding_name: Registered name supporting embedding.
            generation_name: Registered name supporting generation; may match
                ``embedding_name`` for a provider declaring both capabilities.

        Returns:
            Registrations and validated metadata for subsequent construction.

        Raises:
            ValueError: A name is unknown, a capability is unsupported or selected
                metadata fails its validation.
            TypeError: An embedding resolver returns the wrong metadata type.
        """
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
        """Collect nonempty secrets from all registrations for logging redaction."""
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
