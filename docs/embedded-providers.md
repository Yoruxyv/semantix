# Embedded providers and custom integrations

The in-process **semantix-cache** package imports as **semantix_cache**. It is
independent of **semantix-client**, the HTTP client for a Semantix server. The
[embedded core guide](../packages/cache/README.md) describes cache semantics and ownership.

## Install and import

The default install requires NumPy and Pydantic. Optional adapters use HTTPX;
they do not install OpenAI, Anthropic, Google, Hugging Face or Ollama SDKs. Importing
`semantix_cache`, `MemoryStore` or `semantix_cache.adapters` does not load HTTPX.

After publication, install an optional extra with
`python -m pip install 'semantix-cache[openai]'`. The extras `huggingface`, `gemini`,
`ollama`, `anthropic` and `providers` use the same bounded HTTP dependency.
Publication is a separate release action. For a local build, from `packages/cache/`:

~~~text
uv sync --locked --extra dev
uv run --no-sync python -m build
python -m pip install 'dist/semantix_cache-0.1.0-py3-none-any.whl[openai]'
python -m pip install 'dist/semantix_cache-0.1.0-py3-none-any.whl[huggingface]'
python -m pip install 'dist/semantix_cache-0.1.0-py3-none-any.whl[gemini]'
python -m pip install 'dist/semantix_cache-0.1.0-py3-none-any.whl[ollama]'
python -m pip install 'dist/semantix_cache-0.1.0-py3-none-any.whl[anthropic]'
python -m pip install 'dist/semantix_cache-0.1.0-py3-none-any.whl[providers]'
~~~

Import classes from their provider modules, not the package root:

| Module under `semantix_cache.adapters` | Embedding class | Generation class |
|---|---|---|
| `openai` | `OpenAIEmbeddingAdapter` | `OpenAIGenerationAdapter` |
| `huggingface` | `HuggingFaceEmbeddingAdapter` | `HuggingFaceGenerationAdapter` |
| `gemini` | `GeminiEmbeddingAdapter` | `GeminiGenerationAdapter` |
| `ollama` | `OllamaEmbeddingAdapter` | `OllamaGenerationAdapter` |
| `anthropic` | No native API; pair another embedding adapter | `AnthropicGenerationAdapter` |

## 0.1.0 verification

On **2026-10-05**, the maintained adapters passed bounded live embedding and
generation checks with the following configurations. Each MemoryStore flow
generated and wrote on the first miss, then confirmed the repeated-prompt hit
without another generation call. These checks do not cover every model or endpoint.

| Provider | Embedding model (dimensions) | Generation model | Verification |
| --- | --- | --- | --- |
| OpenAI | `text-embedding-3-small` (256) | `gpt-4.1-nano-2025-04-14` | Live verified |
| Gemini | `gemini-embedding-001` (768) | `gemini-3.5-flash-lite` | Live verified |
| Hugging Face | `sentence-transformers/all-MiniLM-L6-v2` (384) | `Qwen/Qwen3-4B-Instruct-2507:nscale` | Live verified |

Independent custom embedding adapters and generation callables for those three
providers also passed the same flow using only public extension interfaces, with
no built-in provider inheritance or private parsing/transport helpers.

**Ollama — prior local test; current evidence incomplete.** The maintainer
previously exercised Ollama locally, but no receipt records the models and exact
cache assertions. No suitable local runtime was available for a fresh check on
2026-10-05. Ollama is not marked live verified for this release; no models were
installed or downloaded to change that status.

**Anthropic — contract verified; first-party live verification pending.**
Generation support is implemented and covered by deterministic contract and
regression tests, but was not live-verified against the first-party Anthropic API
for 0.1.0. Anthropic has no native embedding API; pair generation with any supported
built-in or custom embedding adapter. Claude through Bedrock, Vertex AI, Replicate,
OpenRouter, or another host does not verify the first-party adapter.

First-party Anthropic verification using your own API access is welcome, as are
reproducible compatibility reports and focused fixes with regression coverage
after a defect is reproduced. Never share credentials or commit raw provider
responses. Provider APIs can evolve independently; custom integrations remain the
escape hatch for unsupported versions.

Use the [local provider verifier](provider-live-verification.md) to produce a
fresh sanitized receipt from privately entered credentials. The tool itself does
not promote or demote the evidence above; live runs remain optional and explicit.

## Configuration and ownership

Embedding constructors take keyword-only `client`, `model`, `embedding_space`,
`base_url`, `timeout_seconds=30.0`, and `max_response_bytes=1048576`. Hosted adapters
also require `api_key`; Ollama has no key parameter. Generation constructors use
`max_new_tokens=512` in place of `embedding_space`. No model or credentials are
chosen from environment variables, server settings or a registry.

Base URLs default to the provider's public API. Hugging Face uses separate defaults:
`https://router.huggingface.co/hf-inference/models` for feature extraction and
`https://router.huggingface.co/v1` for chat. Custom hosted URLs must be HTTPS without
userinfo, query or fragment. Ollama accepts an HTTP or HTTPS origin, with no path,
and defaults to `http://localhost:11434`. Gemini accepts model names with or without
`models/`; both forms select the same model.

The client is borrowed: the adapter never creates or closes it. `aclose()` seals
only the adapter; repeated close is harmless. Active requests make close raise
`CacheBusyError`; drain or cancel tasks first. Closed adapters raise `CacheClosedError`.
Adapters support async context management. The cache also borrows the embedder,
store and generation callback, so the application owns their lifetimes.

Each request has a finite total deadline, a streaming byte limit, and no automatic
retry or redirect. The limit checks both declared and received bytes, including
responses without Content-Length. Encoded responses are rejected. The HTTP client
may have its own shorter timeouts; the adapter's total deadline still applies.
HTTP status, transport, timeout, invalid JSON and output failures raise safe
`EmbeddingError` or `GenerationError` with sanitized causal context. Cancellation
propagates. Error messages, repr and package logging do not expose keys, private
URLs or request/response text. The caller owns HTTP hooks, logging and provider data
handling; injecting a client with retries can itself replay requests.

Embedding metadata is explicit and immutable. Its identity must distinguish
provider, model and revision, dimensions, pooling and preprocessing. Never put keys,
private endpoints or user data in it. Matching dimensions alone do not identify the
same space. If a model alias changes behavior, bump the identity and use a matching
store. No automatic fallback switches providers or models.

For `gemini-embedding-001`, the adapter sends the supported top-level
`outputDimensionality` field. The live 768-dimensional check showed that the nested
`embedContentConfig` form returned the default 3072 dimensions instead. Google's
discovery schema marks the top-level field deprecated, although this model still
honors it. Dimension mismatches remain errors; Semantix never truncates or pads a
response to hide a changed provider contract.

The adapters reject boolean, non-finite, wrong-dimension, empty and zero-magnitude
vectors. Hugging Face accepts vectors and singleton batch wrappers; token matrices
use mean pooling. Encode that pooling in its space identity. OpenAI and Ollama require
one returned embedding because each call supplies one text. The cache normalizes
validated vectors for cosine comparison; adapters return the provider's scale.

## Built-in use

This function uses a caller-provided key and generation flow. Choose a supported
OpenAI embedding model and its dimension setting explicitly; the example uses
`text-embedding-3-small`, which accepts a requested dimension count. See the
[OpenAI embedding API](https://developers.openai.com/api/reference/resources/embeddings/methods/create).

~~~python
import httpx

from semantix_cache import AsyncSemanticCache, EmbeddingSpace, GenerationCallable, MemoryStore
from semantix_cache.adapters.openai import OpenAIEmbeddingAdapter


async def answer_questions(api_key: str, generate: GenerationCallable) -> list[str]:
    space = EmbeddingSpace(
        identity="openai:text-embedding-3-small:app-r1:d1536:raw", dimensions=1536
    )
    answers = []
    async with httpx.AsyncClient() as client:
        async with OpenAIEmbeddingAdapter(
            client=client, api_key=api_key, model="text-embedding-3-small", embedding_space=space
        ) as embedder:
            async with MemoryStore(embedding_space=space) as store:
                async with AsyncSemanticCache(embedder=embedder, store=store) as cache:
                    for question in ["weather today", "weather tomorrow"]:
                        result = await cache.resolve(question, generate=generate, namespace="support-v1")
                        answers.append(result.response)
    return answers
~~~

Optional generation wrappers expose `async generate(prompt) -> str`; pass the bound
method as `generate=adapter.generate`. They remain application-owned conveniences;
there is no additional GenerationAdapter protocol or provider lookup in the cache.
Wrap generation yourself when you need RAG, tool execution, moderation or prompt
context. Use `get`/`set` to cache only your application's approved final text.
Version the namespace when generator, context or approval policy changes.

Completion checks deliberately tighten the existing server's text-only parsing:
OpenAI/Hugging Face require `finish_reason="stop"`; Gemini requires `finishReason="STOP"`;
Anthropic requires `stop_reason="end_turn"` or `"stop_sequence"`; Ollama requires
`done=true` and a missing or `"stop"` done_reason. Empty, oversized, truncated,
blocked or tool-call results fail instead of being cached. Gemini thought text is
excluded. Streaming and rich SDK objects are not returned through these wrappers.

The payload conventions are documented by each provider:
[OpenAI chat](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create),
[Hugging Face feature extraction](https://huggingface.co/docs/inference-providers/tasks/feature-extraction)
and [chat](https://huggingface.co/docs/inference-providers/tasks/chat-completion),
[Gemini embeddings](https://ai.google.dev/api/embeddings)
and [generation](https://ai.google.dev/api/generate-content),
[Ollama embeddings](https://docs.ollama.com/api/embed)
and [generation](https://docs.ollama.com/api/generate),
[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create).
Offline parity tests protect common request bodies, authentication, model-path
encoding, pooling and completed-text parsing between the embedded adapters and
server adapters. Their error types and retry/ownership policies remain separate.

## Custom integrations

Any unsupported provider can be integrated structurally: supply the existing
`embedding_space` property and `async embed(text) -> Sequence[float]`. No subclass,
registration, extra dependency or request to add a built-in is required. A bare
embedding callable has no space metadata and is insufficient. Wrap it explicitly;
the complete [custom integration example](../packages/cache/examples/custom_integration.py)
shows this and an object-based async generation flow. The demo is deterministic,
not a production embedding model. From `packages/cache/`, execute and type-check it with:

~~~text
uv run --no-sync python examples/custom_integration.py
uv run --no-sync mypy src tests examples
~~~

This is also the fallback when a provider changes or drops its API. Copy the small
wrapper into your application, replace `demo_model` with your async model integration,
and choose accurate metadata. Custom adapters should raise safe `EmbeddingError`
for expected integration failures. Unexpected programming errors and generation
callback exceptions propagate unchanged. Never silently switch spaces or models.

There is no provider-string registry, so there is no unsupported-provider lookup
error to work around. Use the capability table and structural example when a class
is absent. Anthropic generation can use an existing supported embedding adapter;
a custom embedding integration is optional. A missing HTTP extra reports the exact
installation command and this custom integration path.

## Deprecation path

If a maintained adapter is retired, its constructor will emit a standard
`DeprecationWarning` with a static reason and a link to the custom integration guide.
It will remain callable through at least the following minor release; removal may
occur no earlier than the next minor release after that. Release notes will name
the last supported version and custom replacement. Warnings must never interpolate
credentials, endpoints, prompts or responses. Existing adapters are not deprecated
by this change. Provider model availability remains caller-owned; deprecation will
never select a replacement model or provider automatically.
