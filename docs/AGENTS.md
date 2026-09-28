# Documentation agent instructions

Read [root instructions](../AGENTS.md), [current architecture](../ARCHITECTURE.md), and
[product principles](../DESIGN.md). These rules cover docs, translated guides, and
public repository prose.

## Documentation rules

- Verify factual statements against current implementation, tests, API schemas,
  configuration, and CI. A plan or Graphify node is not proof that a feature exists.
- Keep architecture wiring in ARCHITECTURE.md, durable product principles in DESIGN.md,
  and procedural details in the appropriate guide or runbook. Do not silently document
  planned behavior as implemented.
- Keep capacity and production claims tied to exact workload, hardware, provider,
  topology, source revision, duration, failures, and known limits. Preserve historical
  failed runs and remediation evidence.
- Distinguish the supported two-replica Compose topology and its external TLS boundary
  from untested managed deployment, other replica counts, HA database, and
  hosted-provider capacity.
- Use capability-based public wording. Do not surface internal roadmap or phase labels
  in new public explanations merely because planning files use them.
- Protect secrets, credentials, private prompts/responses, private endpoints, personal
  data, and sensitive production logs. Sanitize examples and screenshots.
- Keep English and Indonesian counterparts synchronized for guides and policies that
  have existing translations under docs/translation/id. Review translation meaning; do
  not mechanically copy changed English.
- Preserve valid relative Markdown links and existing language-switcher targets. Do not
  replace internal paths with site-root links unless that is deliberate. Use the repository
  [Links workflow](../.github/workflows/links.yml) Lychee settings when available,
  and independently check changed relative links and headings.
- Keep commands, paths, identifiers, API field names, and examples executable and
  consistent with the current checkout. Report unavailable validation honestly.
