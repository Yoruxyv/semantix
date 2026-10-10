"""Supported imports for explicit custom server providers.

Start with ``ProviderRegistry`` or ``create_default_provider_registry``, add
``ProviderRegistration`` objects, then pass the registry to
``app.factory.create_app(..., provider_registry=registry)``. Register before
application creation: selection freezes the registry and resolves metadata;
application lifespan subsequently invokes builders with a
``ProviderBuildContext`` containing its borrowed HTTPX AsyncClient.

Declare embedding, generation or both capabilities through the exported
protocols. Supply stable, credential-free metadata and register secrets for
the server's logging redaction; registry metadata checks have narrower scope
than universal credential detection. Adapters must not close the shared
client. Deployment code owns any additional resources an adapter creates.

``post_json`` and ``create_retry_factory`` are optional shared HTTP mechanisms.
Each adapter still owns its endpoints, authentication, request payloads and
response decoding, even when another provider currently uses similar JSON.
This surface does not configure the independent embedded ``semantix_cache``
library. See ``docs/guides/provider-extensions.md`` for the bootstrap example.
"""

from app.providers.factory import create_default_provider_registry
from app.providers.protocols import EmbeddingProvider, GenerationProvider
from app.providers.registry import (
    EmbeddingMetadata,
    ProviderBuildContext,
    ProviderBuilder,
    ProviderCapability,
    ProviderRegistration,
    ProviderRegistry,
    SafeMetadataValue,
)
from app.providers.shared.transport import (
    RetryFactory,
    create_retry_factory,
    post_json,
)

__all__ = [
    "EmbeddingMetadata",
    "EmbeddingProvider",
    "GenerationProvider",
    "ProviderBuildContext",
    "ProviderBuilder",
    "ProviderCapability",
    "ProviderRegistration",
    "ProviderRegistry",
    "RetryFactory",
    "SafeMetadataValue",
    "create_default_provider_registry",
    "create_retry_factory",
    "post_json",
]
