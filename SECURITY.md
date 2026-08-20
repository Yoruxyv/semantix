<p align="center">
  <sub><a href="/docs/translation/id/SECURITY.md">ID</a> · <a href="SECURITY.md">EN</a></sub>
</p>

# Security Policy

Semantix is a local-first semantic-cache laboratory. The explicitly named development stack is intended for one trusted developer and must not be exposed to an untrusted network. A separate hardened single-instance deployment path is provided as a prerequisite for shared use.

## Supported versions

| Version | Supported |
|---|:---:|
| `main` branch | Yes |
| Latest tagged release, when available | Yes |
| Older releases and historical commits | No |
| Third-party forks | No |

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use the repository Security tab, open Advisories, select **Report a vulnerability**, and submit the report privately.

Include the affected commit, deployment mode, endpoint or provider, reproducible steps, expected and observed behavior, realistic impact, sanitized evidence, and a suggested remediation when known.

Remove API keys, access tokens, database passwords, private prompts, complete responses, personal data, and unrelated production information.

## In scope

Useful reports include concrete issues involving:

- exposure of provider credentials, access tokens, imported dataset prompts or
  notes, or cached responses;
- authentication or role bypass;
- namespace authorization failures;
- cross-embedding-space data leakage;
- SQL injection or unsafe pgvector operations;
- server-side request forgery through provider configuration;
- arbitrary file access or command execution;
- exploitable dependency vulnerabilities;
- CORS, trusted-proxy, request-size, or rate-limit boundary failures;
- unintended exposure of cache-management operations;
- migration, Docker, or startup behavior that breaks the documented security boundary.

## Deployment expectations

The development stack uses hot reload, development credentials, automatic migrations, and loopback-only ports. Public exposure of that stack is unsupported.

The hardened stack requires:

- TLS termination before public traffic reaches Semantix;
- token authentication and role/namespace authorization;
- strong secret-managed tokens and database passwords;
- explicit trusted-proxy CIDRs;
- a single backend process unless shared rate-limit storage is added;
- separate migration and runtime database roles;
- no direct public backend or database ports;
- operator review of provider data handling, persistent dataset retention,
  deletion, backup retention, and recovery.

The supplied hardened stack is not a complete multi-tenant service. It does not add distributed coordination, deployment-wide metrics, tenant billing, or a general identity provider.

## Known design limitations

- Rate limiting, metrics, and request coalescing remain process-local. Runtime
  metrics are a global operational surface restricted to global
  administrators; namespace users have scoped cache statistics instead.
- Hosted providers receive prompts selected by authorized operators.
- Private Monitor requests bypass cache reads and writes and are omitted from
  the browser-memory query trace. Their prompt, response, matched content, and
  cache key are not retained as trace evidence.
- When explicitly enabled, the PostgreSQL evaluation catalog stores
  namespace-authorized prompts and notes until expiry or deletion. Database
  backups may outlive application retention and require a separate secure
  erasure policy.
- Semantic similarity remains probabilistic and needs threshold evaluation.
- Access tokens configured through `AUTH_PRINCIPALS` are operator-managed credentials rather than federated identity.
- The default production frontend binds to loopback and depends on an external TLS reverse proxy.

## Out of scope

Please avoid reports based only on model quality, expected provider latency or pricing, documented local-development limitations, attacks requiring control of the trusted host or Docker daemon, dependency scanner output without reproducible impact, or unauthorized testing against third-party infrastructure.

Do not perform destructive testing, access data that is not yours, degrade services, or incur provider charges without explicit authorization.

## Coordinated disclosure

Allow reasonable time for investigation and remediation before public disclosure. Good-faith research that follows this policy and avoids privacy violations or service disruption will be treated as authorized for improving Semantix. This policy does not authorize testing against GitHub, Docker, hosting platforms, or third-party providers.
