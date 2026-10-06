# Repository agent instructions

## Purpose

Semantix is a local-first semantic-cache service and workbench for inspecting cache
decisions, evaluating thresholds, and understanding provider savings and operational
behavior.
Preserve that focus. It is not a generic chatbot, LLM platform, provider marketplace,
billing system, or tenant administration platform.

## Instruction order

Read this file first. Then read [ARCHITECTURE.md](ARCHITECTURE.md) when runtime
structure or ownership matters, [PRODUCT_PRINCIPLES.md](PRODUCT_PRINCIPLES.md) when product decisions matter,
and the nearest applicable subtree instructions:

- [apps/server/AGENTS.md](apps/server/AGENTS.md) for the FastAPI service and tests.
- [apps/web/AGENTS.md](apps/web/AGENTS.md) for the React workbench and tests.
- [packages/client/AGENTS.md](packages/client/AGENTS.md) for the public Python client.
- [ops/AGENTS.md](ops/AGENTS.md) for deployment, CI, smoke, and load tooling.
- [docs/AGENTS.md](docs/AGENTS.md) for documentation and translations.

Finally inspect relevant current source, tests, schemas, migrations, configuration, and
runbooks. More specific instructions may refine these rules; they do not override
repository-wide safety or correctness requirements. Root Compose files and cross-area
workflow changes also require the relevant subtree guidance.

## Sources of truth

Resolve disagreements in this order:

1. Current implementation.
2. Current automated tests.
3. Current API schemas, runtime contracts, and migrations.
4. Current configuration and CI.
5. Current documentation.
6. Planning material.
7. Graphify output.

Verify claims against executable behavior. A plan is not evidence that a capability
exists.

## Before editing

- Inspect git status, current branch, and intended base. Never overwrite, discard, or
  silently incorporate unrelated work.
- Identify the owning feature and read its applicable instructions.
- Establish current behavior, including callers and boundary conditions for a bug fix.
- Read the relevant tests, public contracts, and configuration. When a task names a
  plan, read it fully, verify its current-state claims, and implement only its active scope.
- Identify the smallest relevant validation commands before implementation.
- Use a focused conventional branch such as docs/short-description; never push directly
  to a protected or default branch. Do not create codex/ branches. Do not rewrite
  unrelated history; use force-with-lease only for an explicitly approved rewrite.

## Scope and engineering

- Keep one concern per change. Do not bundle unrelated refactors, broad reformatting,
  unrelated TODOs, or optional future work. Record unrelated defects separately; fix them
  here only when they block this task or pose an immediate correctness or security issue.
- Do not add speculative architecture or dependencies without evidence that existing
  code, the standard library, or installed dependencies cannot meet the need.
- Do not silently change a public API, SDK signature, configuration meaning, persisted
  data contract, or documented security boundary. Review consumers and compatibility.
- Do not weaken or rewrite tests merely to obtain a pass. Behavior-changing bug fixes
  need a regression check unless impractical; report that limitation.
- Prefer clear, correct behavior to cleverness. Keep resource ownership explicit and
  release owned resources on success, error, and cancellation.
- Give newly introduced externally blocking operations finite timeouts. Propagate
  cancellation unless the owning layer intentionally translates it.
- Preserve meaningful failures and stable public errors; do not broadly swallow
  exceptions.
- Keep exception handlers hierarchy-minimal. Do not list a subclass when a caught
  superclass already covers it. Verify third-party exception inheritance before
  simplifying handlers; static-analyzer silence is not proof that an exception tuple
  is nonredundant.
- Validate untrusted inputs at their boundary. Do not log or commit secrets, tokens,
  private endpoints, private prompts or responses, personal data, or production logs.
- Treat generated output, local caches, credentials, and machine-specific hooks as local
  artifacts unless a separate reviewed change adopts them.
- Use evidence before increasing architectural complexity. Tests and documentation are
  part of behavior changes.

## Graphify navigation

Use the local code-only graph before broad source browsing when it can identify
ownership, imports, callers, routes, or dependencies. From the repository root, query
graphify-out/graph.json; if absent, create it with graphify extract . --code-only and
graphify cluster-only . when useful. Graphify is a map, not an authority: verify
findings in current source and tests.

Refresh with graphify update . after validated source changes that alter files, symbols,
imports, calls, inheritance, routes, or dependency wiring. Documentation-only changes do
not need a refresh. Keep graphify-out/ and .codex/ untracked.

## Completion

- Run the smallest relevant checks and any required quality gate; state exactly what ran
  and what could not run.
- Validate changed documentation links when applicable.
- Run git diff --check and git status --short.
- Review the complete final diff for scope, correctness, secrets, and generated
  artifacts. For AI-assisted changes, understand every changed line, verify licenses and
  attribution, and remove fabricated claims.
- Report branch, changed files, validation results, unresolved findings, and material
  limitations. If committing or preparing a PR, use an accurate Conventional Commit
  title and complete the PR template honestly. Do not create or merge a PR unless
  requested.
