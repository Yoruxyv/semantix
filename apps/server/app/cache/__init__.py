"""Server semantic-cache matching, administration and storage boundaries.

``application.service.SemanticCache`` coordinates embedding, compatible candidate
search, threshold eligibility and confirmed-hit evidence. ``domain`` owns keys,
namespaces, models, vector validation and backend protocols. Shared semantic
primitives come from the embedded package through server boundary wrappers; the
server retains its own HTTP contract and administration behavior.

``api`` exposes inspection, mutation and threshold routes; authentication and
namespace authorization remain server-owned. ``infrastructure.factory`` selects
the configured backend. ``infrastructure.backends`` contains memory and pgvector
implementations; cache SQL/migrations remain in ``infrastructure``. The lifespan
supplies the embedding service and, when needed, a shared PostgreSQL pool.

Filter namespaces and embedding spaces before matching, preserve expiry and
revision-aware hit confirmation, and keep foreign entry details undisclosed.
The server's pgvector backend is distinct from embedded PgVectorStore: their
schema ownership, migrations and public usage contracts are separate.

Start with the application service and domain protocols, then the selected
backend and focused cache tests. Query generation/policy orchestration belongs to
``app.query``; controlled evaluation caches belong to ``app.benchmark``.
"""
