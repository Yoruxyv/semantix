## Description

<!-- Explain the problem and the implemented change directly. -->

## Changes

<!-- List the important implementation changes. -->

-
-

## Type of change

- [ ] `feat` — new functionality
- [ ] `fix` — bug fix
- [ ] `docs` — documentation only
- [ ] `style` — formatting with no behavior change
- [ ] `refactor` — internal restructuring
- [ ] `perf` — measured performance improvement
- [ ] `test` — test-only change
- [ ] `chore` — maintenance
- [ ] `ci` — CI workflow change
- [ ] `build` — dependency or build-system change

## Areas affected

- [ ] Frontend
- [ ] Backend
- [ ] Query workflow
- [ ] Cache behavior
- [ ] Provider adapters
- [ ] Benchmarking
- [ ] Observability or load testing
- [ ] pgvector or migrations
- [ ] Docker or configuration
- [ ] Documentation

## Verification

<!-- Include the exact commands you ran and their results. -->

```text
# Example:
# cd apps/server
# python -m pytest
# python -m ruff check .
```

## Screenshots or evidence

<!--
Required for visible UI changes.
For performance changes, include reproducible before/after measurements and
the provider, model, dataset, threshold, hardware, and cache conditions.
Remove this section when it does not apply.
-->

## Configuration and compatibility

- [ ] No environment variables changed
- [ ] `.env.example` was updated
- [ ] API contracts remain backward-compatible
- [ ] API documentation/types were updated
- [ ] No database migration is required
- [ ] Migration behavior was documented and tested
- [ ] Embedding-space compatibility was considered
- [ ] Existing provider and cache defaults remain unchanged

## AI assistance

<!--
Disclosure is required when an AI tool materially contributed to this pull
request.

Examples include:
- generating or modifying source code;
- generating tests;
- translating or drafting documentation;
- debugging or refactoring;
- repository analysis;
- generating implementation suggestions incorporated into the change.

Do not include private prompts, conversation transcripts, credentials, API keys,
or other sensitive information.

Repository-maintained automation such as Dependabot is exempt.
-->

- [ ] No AI tool materially contributed to this change
- [ ] AI tools materially assisted this change

If AI-assisted, briefly describe the tool and how it was used:

<!--
Example:
Claude Code was used for repository analysis and implementation drafting.
I reviewed the resulting changes and ran the verification listed above.
-->

## Checklist

- [ ] My branch contains one focused concern
- [ ] I reviewed and understand every changed line
- [ ] I added or updated relevant tests
- [ ] I updated relevant documentation
- [ ] I ran the affected backend checks
- [ ] I ran the affected frontend checks
- [ ] I validated Docker Compose when applicable
- [ ] I did not commit credentials, private prompts, responses, or personal data
- [ ] Provider tests do not call real external services
- [ ] Performance claims include reproducible evidence
- [ ] Any AI-assisted changes were manually reviewed, verified, and accurately disclosed

## Related issue

<!-- Example: Closes #123 -->
