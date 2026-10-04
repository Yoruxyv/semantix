"""Optional provider integrations for embedded semantic caching.

An embedding adapter turns text into a vector in an explicitly declared
``EmbeddingSpace``. Generation remains an application-owned async prompt-to-text
callable. These are separate integrations: the cache has no provider registry,
automatic model selection or server configuration dependency.

Navigating the maintained modules
--------------------------------
``openai``
    ``OpenAIEmbeddingAdapter`` and ``OpenAIGenerationAdapter``.
``huggingface``
    ``HuggingFaceEmbeddingAdapter`` and ``HuggingFaceGenerationAdapter``.
``gemini``
    ``GeminiEmbeddingAdapter`` and ``GeminiGenerationAdapter``.
``ollama``
    ``OllamaEmbeddingAdapter`` and ``OllamaGenerationAdapter``.
``anthropic``
    ``AnthropicGenerationAdapter``; use a custom integration for embeddings.

Import classes explicitly from their provider module, for example::

    from semantix_cache.adapters.openai import OpenAIEmbeddingAdapter

Install the corresponding extra (``openai``, ``huggingface``, ``gemini``, ``ollama``,
``anthropic``), or ``semantix-cache[providers]``. These adapters use optional HTTPX
rather than provider SDKs. Importing ``semantix_cache`` or this namespace does not
import provider modules or HTTPX.

Configuration, lifetime and output
----------------------------------
Constructors take a caller-owned HTTPX AsyncClient, an explicit model and, for
embeddings, an explicit space identity/dimensions. Hosted adapters take an API key;
Ollama does not. Keep identity stable for the same provider/model/revision,
preprocessing and pooling, and change it when those semantics change. Matching
vector lengths alone is insufficient. Keep credentials out of space identity.

Adapters support ``async with`` and ``aclose()``; they borrow and never close the
HTTP client. Drain/cancel requests before closing the adapter, then close clients
your application owns. Requests have bounded response sizes and total deadlines;
adapter code does not automatically retry generation. Generation adapters return
completed text through ``async generate(prompt)``; pass the bound method as
``generate=adapter.generate`` to the cache.

Custom integrations
-------------------
Implement the structural ``EmbeddingAdapter`` (``embedding_space`` plus async
``embed(text)``), or supply your own async generation function/callable. This path
supports application-specific workflows and unsupported provider versions without
changing Semantix. Built-ins target documented provider APIs; external APIs can
change independently. The core does not promise permanent provider behavior.

Consult the guide for model/URL configuration, supported payloads, lifecycle,
error handling and executable integration examples:
https://github.com/Yoruxyv/semantix/blob/main/docs/embedded-providers.md.
"""
