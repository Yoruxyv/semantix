# Custom provider adapters

Semantix deployments can register trusted server-side provider adapters without
editing the built-in provider factory. Registration is explicit in the server
bootstrap: there is no package scanning, entry-point discovery, import-path
configuration, hot reload, or request-time provider switching.

The supported extension imports are in `app.providers.extension`. The Python
HTTP SDK remains unaware of provider adapters, credentials, and configuration.

## Minimal deterministic provider

Set the selected names in the server environment:

```env
EMBEDDING_PROVIDER=example-deterministic
GENERATION_PROVIDER=example-deterministic
```

Then expose an application object from a deployment-owned module such as
`custom_app.py`:

```python
from collections.abc import Sequence

from app.core.config import Settings
from app.factory import create_app
from app.providers.extension import (
    EmbeddingMetadata,
    ProviderRegistration,
    create_default_provider_registry,
)


class ExampleProvider:
    async def create_embedding(self, text: str) -> Sequence[float]:
        return [1.0, 0.0, 0.0]

    async def generate(self, prompt: str) -> str:
        return f"example: {prompt}"


settings = Settings()
registry = create_default_provider_registry(settings)
registry.register(
    ProviderRegistration(
        name="example-deterministic",
        capabilities=frozenset({"embedding", "generation"}),
        builder=lambda _context: ExampleProvider(),
        embedding_metadata=EmbeddingMetadata(
            dimensions=3,
            space="example-deterministic:embedding-v1",
        ),
        generation_metadata={
            "provider": "example-deterministic",
            "model": "deterministic-v1",
        },
    )
)
app = create_app(settings, provider_registry=registry)
```

Run that module with `uvicorn custom_app:app`. Normal `uvicorn app.main:app`
startup still creates the complete built-in registry automatically.

The example implements both structural protocols. Because the same
registration is selected for both capabilities, its builder runs once and the
same instance serves embedding and generation requests. Embedding-only and
generation-only registrations declare only the capability they implement.

## Registration contract

`ProviderRegistration` contains only startup metadata with a current runtime or
safety purpose:

- `name`: 1-50 characters matching
  `[A-Za-z0-9][A-Za-z0-9._:-]{0,49}` (aligned with persisted evaluation
  metadata);
- `capabilities`: `embedding`, `generation`, or both;
- `builder`: a synchronous startup factory receiving `ProviderBuildContext`;
- `embedding_metadata`: positive dimensions and a stable embedding-space
  identity when embedding is supported;
- `generation_metadata`: non-empty, non-secret scalar values used by existing
  evaluation and diagnostic fingerprints when generation is supported;
- `secrets`: optional non-empty Pydantic `SecretStr` values added to the
  existing log-redaction set.

Settings accepts any syntactically valid provider name. Application creation
then freezes the registry and resolves the selected capabilities. Unknown
names, capability mismatches, incomplete metadata, duplicates, attempts to
replace built-ins, and mutation after freeze fail before query traffic begins.
Built-in provider field, URL, model, dimension, and credential validation
remains unchanged.

Embedding dimensions are resolved before startup completes. The existing
`EmbeddingService` still rejects wrong-sized, non-finite, zero-magnitude, and
otherwise invalid returned vectors. Dimensions alone do not establish cache
compatibility: `EmbeddingMetadata.space` must identify the provider, model,
version, and other stable semantics that affect vectors. It must not contain
credentials, timestamps, process IDs, or other volatile values. The resolved
identity flows through `ProviderBundle` into pgvector cache construction, so
equal-dimensional but incompatible custom providers remain isolated.

Generation metadata should contain only stable, non-secret execution identity
needed to compare evaluation runs, such as a provider label and model/version.
Do not put URLs, credentials, or complete custom configuration objects in this
mapping. Registered secret values are rejected if they appear in embedding or
generation identity metadata.

## Configuration and lifecycle

Custom configuration belongs to the deployment. Validate it in the bootstrap
and capture it in the builder; do not add generic custom-provider fields to
Semantix `Settings`:

```python
custom_config = MyProviderSettings()

registry.register(
    ProviderRegistration(
        # metadata omitted here
        builder=lambda context: MyProvider(
            config=custom_config,
            client=context.client,
        ),
    )
)
```

`ProviderBuildContext.client` is the server-owned shared `httpx.AsyncClient`.
It has the configured finite provider timeout, is reused across requests, and
is closed by Semantix on shutdown or startup failure. The context also exposes
the bounded `provider_timeout_seconds` and `provider_max_response_bytes`
policies without exposing the complete Semantix settings object. Provider
builders run once during lifespan startup, never per request.

Prefer the shared client. If an adapter must own another client or resource,
the deployment that creates that resource must also close it during deployment
shutdown; the registry is intentionally not a generic resource manager. A
registration must not create an unmanaged client per request.

## HTTP and trust boundary

For JSON-over-HTTP adapters, `app.providers.extension` also exports the
supported `post_json`, `create_retry_factory`, and `RetryFactory` transport
surface. `post_json` preserves the existing bounded streamed reads,
`Accept-Encoding: identity`, encoded-response rejection, provider error
mapping, and bounded retry contract. Pass
`context.provider_max_response_bytes` when the default response bound is not
appropriate for the deployment configuration.

A custom adapter is explicitly installed deployment-time Python code. It runs
with the same process privileges as Semantix and can choose not to use the
shared client or hardened transport. The registry is a deterministic
composition boundary, not a sandbox. The deployment is responsible for
reviewing custom code, enforcing equivalent finite timeouts and response
bounds for custom transports, protecting credentials, and avoiding sensitive
logs. Deterministic non-network adapters remain valid.

Health and diagnostics expose only the validated provider names and existing
non-secret fingerprints. They do not expose registration objects, provider
URLs, models, credentials, or custom configuration.
