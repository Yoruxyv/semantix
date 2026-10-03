# Frontend agent instructions

Read [root instructions](../../AGENTS.md), [current architecture](../../ARCHITECTURE.md), and
[product principles](../../DESIGN.md) first. These rules cover apps/web/src, tests, and
frontend build configuration.

## Feature ownership

- Keep Monitor, Cache, Evaluations (features/benchmark), Observability, and Auth pages,
  components, hooks, API adapters, types, decoders, and route definitions with their
  owning feature. src/app/router composes routes; src/shared holds genuinely shared
  HTTP, query, UI, and validation helpers.
- Use existing React Query for server data and local React state/context for feature
  state. Add global state only when a demonstrated cross-route lifetime needs it. Do not
  create generic abstractions for one feature.
- Treat every HTTP response as unknown until the owning feature decoder validates it.
  Keep feature types and decoders synchronized with backend public schemas and tests.
  Keep API errors, loading, empty, and success states explicit.
- Preserve strict TypeScript, noUncheckedIndexedAccess, and exactOptionalPropertyTypes.
  Do not add any, an unsafe cast, or an ESLint suppression just to bypass a contract
  defect.

## Security and accessibility

- Client role checks may hide unavailable controls; backend authorization is
  authoritative. Preserve namespace-aware query keys and clear protected state on
  principal changes. Do not put secrets in VITE_* variables.
- Keep imported dataset content in session-local component state unless persistence is
  explicitly requested. Validate again on the backend, render user text as text, and
  neutralize spreadsheet formulas in CSV exports and preserve JSON structure. Exports
  must be deliberate user actions. Do not
  persist sensitive prompts in localStorage,
  sessionStorage, IndexedDB, or service-worker caches without explicit scope.
- Use semantic elements and labeled native controls where possible. Preserve keyboard
  access, visible focus, route/dialog focus behavior, meaningful status announcements,
  non-color labels, chart alternatives, and usable narrow layouts. Do not clip dense
  content to hide overflow.
- For navigation or layout changes, check 320, 744, 768, 820, 834, 1024, and 1280 px,
  representative landscape widths, 200% zoom, keyboard operation, and page-level
  overflow. Update [accessibility reference](../../docs/reference/accessibility.md) when
  its contract changes. Preserve query, hash, filter, and route state in compatibility
  redirects.
- Do not silently add another top-level workspace or turn Monitor into a generic
  chatbot.

## Validation

- Add focused Vitest tests for changed hooks, decoders, API adapters, or components. Use
  Playwright/axe for affected route, responsive, keyboard, or accessibility behavior.
- From apps/web, run the relevant focused npm run test -- <path>. Main gates from
  [package.json](package.json) and CI are npm run lint, npm run format:check, npm run
  imports:check, npm run test:coverage, and npm run build. Run browser tests when their
  behavior is touched.
