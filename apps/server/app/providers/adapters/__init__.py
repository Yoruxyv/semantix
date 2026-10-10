"""Maintained server adapters for hosted APIs, Ollama and deterministic mock use.

Each provider module owns its model endpoints, authentication, request payloads
and response decoding. Similar OpenAI and Hugging Face JSON shapes do not bind
their independently evolving APIs to one parser. Reuse common transport and
validation mechanisms from ``app.providers.shared`` where applicable.

``app.providers.factory`` registers and constructs these adapters with a
borrowed client; ``app.providers.extension`` is the custom integration surface.
See ``docs/guides/providers.md`` and ``docs/guides/provider-extensions.md``.
"""
