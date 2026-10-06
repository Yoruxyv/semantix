# Maintained reuse-quality corpus

[cases.jsonl](cases.jsonl) is a checked-in, Semantix-owned benchmark asset: one
synthetic response-reuse case per line, containing an ID, category, split, source
prompt/response, candidate prompt, expected reuse label, task context and notes.
These inputs are intended for maintainer label review, never production/user data.
The current review state is recorded truthfully in the manifest.

[corpus.manifest.json](corpus.manifest.json) records corpus version, schema_version,
provenance, canonical cases SHA256, split policy and label-review status. Corpus
version describes the dataset; schema_version describes its machine-readable contract.

calibration cases select thresholds. held_out cases evaluate those fixed choices
and must not retune them. Prompt families do not cross splits; labels are balanced
within every category/split. This authored holdout is excluded from calibration,
not unseen by its author or representative production traffic.

Canonical hashing decodes strict UTF-8, maps CRLF/CR to LF, strips final LFs and
appends one LF before SHA256. Unicode, spaces and JSON field order remain intact.
Generate the stored SHA from actual cases content and verify it on every validation;
never manually maintain a digest or hard-code one into benchmark logic.

The first checked-in/public corpus is 1.0.0. Uncommitted drafting iterations do not
bump it. After a corpus version is checked in or published:

- patch: reviewed correction to existing cases/labels;
- minor: compatible dataset/category expansion;
- major: incompatible corpus interpretation/methodology change.

Intentional corpus edits require a recomputed hash and renewed label review; version
them under that policy and explicitly regenerate/review public benchmark evidence
from clean accepted source. Stale receipts must fail validation, never auto-update.
See the [feature README](../README.md) for review and regeneration commands.

[workloads.json](../../workloads.json) belongs to runtime/performance benchmarking.
It is unrelated to this reuse-quality corpus and stays at the benchmarks top level.
Raw scores and temporary review views are generated, ignored artifacts; these input
files remain maintained, checked-in assets.
