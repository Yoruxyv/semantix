"""Shared PostgreSQL lifecycle, migrations and server coordination.

``lifecycle.database_pool_lifespan`` owns the optional shared pool used by enabled
cache, evaluation and coordination features. ``database`` supplies pool primitives
and the shared migration machinery; ``migrate`` is the configured migration entry
point. Feature-owned SQL stays under cache/benchmark infrastructure, while shared
coordination migrations live here.

``coordination`` and ``coordination_database`` provide shared rate buckets,
authentication lockouts and the mutable global threshold. Feature services borrow
the lifespan's pool instead of opening per-request pools.

Migration application uses ordered resources, checksums, an advisory lock and
transactions. Preserve the separately authorized migration/runtime role boundary
in hardened deployments. The server schema and migration history are independent
of an application's embedded PgVectorStore schema. Consult
``docs/operations/deployment.md`` and infrastructure/migration tests before
changing startup, grants, recovery or persisted data contracts.
"""
