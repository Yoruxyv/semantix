"""Server provider ports, configuration, selection and HTTP adapters.

``protocols`` defines embedding and generation boundaries. ``configuration`` and
``registry`` validate explicit selections and their embedding-space metadata;
``factory`` builds the selected provider bundle. ``extension`` supplies the
server's custom-provider integration path. ``adapters`` owns provider-specific
payloads, while ``shared`` owns transport, URL, response and vector helpers.

The application factory resolves selection at startup. The lifespan creates one
HTTPX AsyncClient and lends it to provider adapters; adapters do not own the
server's transport lifetime. Provider failures must become existing safe error
contracts before crossing the HTTP boundary. Never expose credentials, private
URLs or request/response payloads through diagnostics.

Server selection is separate from ``semantix_cache.adapters``: embedded callers
supply their own embedder/generation callable and HTTP client. Maintained provider
APIs can change independently; preserve custom integration paths and stable
embedding-space identity when changing adapters. See ``docs/guides/providers.md``,
``docs/guides/provider-extensions.md`` and provider/parity tests.
"""
