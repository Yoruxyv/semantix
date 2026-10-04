"""Interactive query contracts and cache/generation orchestration.

Start with ``api.router`` and ``api.schemas`` for the public query boundary,
``application.service.QueryService`` for execution, and ``domain.policies`` /
``domain.normalization`` for cache mode and matching-text rules.
``application.coalescing`` owns process-local sharing of compatible
in-flight query work; it is separate from persistent cache storage.

QueryService borrows SemanticCache, the generation provider and metrics from the
application lifespan. It coordinates policy, lookup, generation and response
evidence; cache matching/storage belongs to ``app.cache``, provider HTTP belongs
to ``app.providers``, and principal/namespace authorization belongs to the HTTP
security boundary. Bypass/private never read or write live cache entries;
read-only never writes and refresh never reads.

Changes to query schemas must be checked against the web decoders and
``semantix_client`` response models. See ``docs/reference/api.md`` and the query
API/application tests for exact behavior, failure and concurrency contracts.
"""
