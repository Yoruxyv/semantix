# Supply-chain security

Semantix pins every Dockerfile base image and Compose service image to an
immutable multi-architecture manifest digest while retaining its readable tag.
The approved source of truth is
[`ops/supply-chain/approved-images.json`](../../ops/supply-chain/approved-images.json).

## Supported container platforms

Container builds support:

- `linux/amd64`
- `linux/arm64`

The quality workflow builds every production and development Dockerfile for
both platforms. `ops/ci/verify_image_pins.py` rejects mutable references,
unknown images, digest drift, and approvals that omit a supported platform.

## Image updates

Dependabot checks Docker, GitHub Actions, Python, and npm dependencies every
Monday at 04:00 UTC. It opens reviewable pull requests and never auto-merges
them. Routine minor and patch updates are grouped by ecosystem and dependency
type. Version-update queues are capped at one GitHub Actions pull request and
two pull requests for each language package ecosystem.

Major upgrades are handled manually so runtime declarations, CI, documentation,
and compatibility checks move together. Routine Docker version pull requests
are disabled because image updates must also change the reviewed multi-platform
digest in the approved-image manifest. Dependabot security updates remain
enabled and are reviewed as soon as they are published.

Automatic Dependabot rebases are disabled to avoid rerunning the full quality
workflow after every unrelated merge. Update a dependency branch once, after
its preceding changes are merged, by commenting `@dependabot rebase` on the
pull request before final review.

For an image update:

1. Read the publisher's release and security notes.
2. Confirm the proposed manifest contains both supported platforms.
3. Update the readable tag, digest, and approved-image manifest together.
4. Review every changed digest instead of approving a bot PR from its title.
5. Require the complete `Quality gate`, including both platform builds and
   security scans.

Review routine digest updates weekly. Review publisher security advisories as
soon as they are published and prioritize an emergency digest update when an
actively exploitable issue affects Semantix. Digest-update pull requests are
never exempt from normal quality checks.

## Security checks

The quality workflow adds these checks without changing its default
`contents: read` permission:

| Check | Failure policy |
|---|---|
| CodeQL | New Error, High, or Critical alerts on changed lines |
| TruffleHog | Verified committed credentials |
| Grype image scan | High or Critical vulnerabilities with an available fix |
| Dependency review | High or Critical dependency changes |

The existing React Router advisory exception remains limited to
`GHSA-qwww-vcr4-c8h2`. It applies only to dependency review and does not alter
CodeQL, secret scanning, image scanning, or SBOM generation.

CodeQL receives `security-events: write` only in its job so it can upload
results. Other new jobs remain read-only. GitHub downgrades write permissions
for pull requests from forks; no scanner uses `pull_request_target`, repository
secrets, or privileged registry credentials.

Scanner changes must be exercised in a throwaway fork or non-default branch.
Use only a scanner-provided synthetic fixture, never a live credential. Confirm
that a finding at the documented threshold fails, a lower-severity image
finding does not fail, and the fixture is absent before merging.

## SBOM and provenance artifacts

After image scanning succeeds, CI builds both production images and publishes
one artifact named:

```text
semantix-supply-chain-<commit-sha>
```

It contains:

- `backend.spdx.json`
- `frontend.spdx.json`
- `backend.provenance.json`
- `frontend.provenance.json`

SBOMs use SPDX JSON. Provenance files contain full Buildx build metadata and
materials. Workflow artifacts expire after 14 days. These pull-request
artifacts improve review visibility but are not signed release attestations.

## Release automation decision

Automated releases are intentionally not configured yet. The repository does
not define:

- a release target or container registry;
- a versioning and tag scheme;
- a signing or hosted-attestation requirement;
- a rollback owner and procedure.

The maintainers must agree on all four before a release workflow is added.
Until then, CI builds test artifacts only and does not publish images,
packages, tags, or GitHub releases.
