# Semantix documentation

Use this index to find the detailed guide for the task at hand. The repository
root [README](../README.md) remains the short project overview and quick start.

## Guides

| Guide | Use it for |
|---|---|
| [Getting started](guides/getting-started.md) | Environment files, local toolchains, Docker workflows, and troubleshooting |
| [Providers](guides/providers.md) | Hugging Face, OpenAI, Anthropic, Gemini, Ollama, and mock configuration |
| [Custom provider adapters](guides/provider-extensions.md) | Explicit trusted server-side adapter registration and lifecycle contract |
| [pgvector](guides/pgvector.md) | Persistent cache storage, ports, migrations, and database verification |
| [Cache policies](guides/cache-policies.md) | Thresholds, TTL, LRU, namespaces, privacy, and request coalescing |
| [Benchmarking](guides/benchmarking.md) | Datasets, metrics, safeguards, projections, and exports |
| [Evaluation history](guides/evaluation-history.md) | Durable aggregate run history, retention, namespaces, comparison compatibility, and recovery |
| [Prompt normalization](guides/prompt-typo-normalization.md) | Optional typo-correction behavior and limitations |
| [Python SDK](../sdk/README.md) | Install and use the typed sync and async public HTTP clients |
| [Development](guides/development.md) | Supported toolchains, quality checks, architecture rules, and contributions |

## Reference

| Reference | Use it for |
|---|---|
| [API](reference/api.md) | Endpoints, authentication, requests, responses, and error contracts |
| [Evaluation dataset schema v1](reference/evaluation-dataset-schema-v1.md) | Imported JSON fields, validation codes, limits, persistence, and retention |
| [Architecture](reference/architecture.md) | Runtime flow, feature ownership, boundaries, and deployment constraints |
| [Accessibility](reference/accessibility.md) | Accessibility expectations and verification commands |

## Operations

| Runbook | Use it for |
|---|---|
| [Hardened deployment](operations/deployment.md) | Authentication, roles, proxies, TLS, request limits, and database permissions |
| [Operations and recovery](operations/recovery.md) | Credential rotation, backup, restore, cache rebuild, rollback, and incidents |
| [Load testing](operations/load-testing.md) | Safe k6 scenarios and runtime observability |
| [Supply-chain security](operations/supply-chain.md) | Image pins, security scans, SBOM/provenance artifacts, and dependency updates |
