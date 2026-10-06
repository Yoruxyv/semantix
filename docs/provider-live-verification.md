# Provider live verification

The repository verifier checks one maintained embedded provider path against its
first-party API. A PASS records the exact model, source commit, UTC date and optional
challenge. It proves a bounded miss, generation, write and authoritative repeated
hit with no second generation, followed by resource cleanup. It does not certify
every model, future API compatibility, semantic reuse safety or production quality.

Ordinary contributors do not need to buy API credit or run live verification.
Deterministic tests require no provider credentials or network calls. Run live
verification only when you deliberately authorize the provider requests and cost.

## Run locally

From the repository root, prepare the existing development environment:

~~~text
uv sync --project packages/cache --locked --extra dev
uv run --project packages/cache --no-sync python scripts/provider_live_verify.py --help
uv run --project packages/cache --no-sync python scripts/provider_live_verify.py openai --challenge semantix-review-a1b2
~~~

The default credential entry uses non-echoing local getpass. If a secure terminal
is unavailable, the verifier stops instead of falling back to echoed input.
Never paste a key into chat, an issue, a PR, a screenshot or CLI arguments.

An explicit --use-env reads only the selected conventional variable:
OPENAI_API_KEY, GEMINI_API_KEY, HF_API_KEY or ANTHROPIC_API_KEY. It does not read
.env files, print environment values, or inherit proxy/base-URL settings. Without
--use-env, an existing environment key does not bypass the secure prompt.

The stdout output is one JSON receipt; stderr contains a short safe summary.
The authoritative model and checked-in structural JSON Schema are in
[models.py](../scripts/provider_live_verification/models.py) and
[provider_live_receipt.schema.json](../scripts/provider_live_receipt.schema.json).
The Python validator also checks cross-field PASS invariants. No response text,
prompt, HTTP body/header, credential, account/project identifier or exception detail
is written. The verifier writes no receipt file; inspect only its sanitized output
before sharing it. --challenge round-trips unchanged and is a public freshness
marker, not authentication or cryptographic proof. Never put a secret in it.

The invocation above remains the executable entrypoint. Implementation stays in
scripts/provider_live_verification: cli owns argument/credential/output handling,
models owns configuration and receipt validation (including the metadata secret
guard), providers owns adapter selection and bounded first-party transport, and
runner owns observed cache flow, resource cleanup and task inspection. The package
initializer exposes no runtime API.

## Provider and model scope

| Provider | Generation default | Embedding default (dimensions) |
| --- | --- | --- |
| OpenAI | gpt-4.1-nano-2025-04-14 | text-embedding-3-small (256) |
| Gemini | gemini-3.5-flash-lite | gemini-embedding-001 (768) |
| Hugging Face | Qwen/Qwen3-4B-Instruct-2507:nscale | sentence-transformers/all-MiniLM-L6-v2 (384) |
| Ollama | gemma3:4b | embeddinggemma (768) |
| Anthropic | Explicit --model required | deterministic-local-v1 (2), not Anthropic embeddings |

The first three defaults match the existing dated configurations in the
[provider guide](embedded-providers.md#010-verification); they are not promises
that a model remains available to every account. --model records an explicit
generation override. An embedding override requires both --embedding-model and
--embedding-dimensions. Dimensions remain validated; vectors are never padded or
truncated. Model names must be explicit bounded identifiers; no discovery,
fallback, retry or substitution occurs.

For Anthropic, replace YOUR_EXACT_MODEL with a model you can access:

~~~text
uv run --project packages/cache --no-sync python scripts/provider_live_verify.py anthropic --model YOUR_EXACT_MODEL --challenge semantix-review-a1b2
~~~

This uses the maintained Anthropic generation adapter at api.anthropic.com,
deterministic local embeddings and MemoryStore. Bedrock, Vertex AI, OpenRouter,
Replicate and other gateways do not prove this first-party path.

Ollama uses localhost:11434 and the native local API. Install/start the service and
supply the requested exact models separately if needed; this tool never installs,
starts, pulls, downloads or changes models. Connection failure or HTTP 404 means
UNAVAILABLE in this environment, not a failed provider contract. Other failures,
including timeout, malformed output or wrong dimensions, mean FAIL.
[Ollama status definitions](https://docs.ollama.com/api/errors).

## Bounds and receipt interpretation

Default total execution timeout is 60 seconds, including a reserved five-second
cleanup budget. --timeout accepts 10 through 120 seconds. Each request has a
deadline of min(15 seconds, (total - 5) / 3). Secure interactive credential entry
and bounded Git metadata inspection happen before this execution budget.

The fixed maximum is three HTTP dispatches for embedding-plus-generation providers:
first embed, first generation and second embed. Anthropic has one HTTP dispatch.
--max-attempts can lower the budget, never raise it. The owned HTTP transport has
zero retries, no redirects, no proxy inheritance and a one-connection bound.
Output is capped at 64 generation tokens through the existing adapter option;
existing bounded response parsing still applies. A model that needs more tokens
may fail; the tool does not weaken completion checks to make it pass.

The receipt records schema_version 1.0.0, source commit/branch/source_dirty,
date/Python/platform, exact models/dimensions/overrides, first-party source and
adapter path, budgets, observed HTTP category/call/write/confirmation counts,
miss/hit/output-equality/ownership assertions, retry count, cleanup status, pending
run-created tasks, result and a fixed safe failure category. Failed calls count as
attempted calls; writes and hits count only after successful public store operations.
The task count excludes tasks already present when the run started.

Exit codes: PASS 0; FAIL 1; UNAVAILABLE/input problem 2; verifier defect 3;
cancellation 130. A defect is deliberately not converted into a provider FAIL
receipt. No raw exception traceback is printed by the CLI. Cancellation propagates
through the async runner while its owned resources are cleaned up. Failed cleanup
or pending run-created tasks prevents PASS.

source_dirty is truthful. A dirty-tree receipt is useful for local diagnosis but
cannot identify the exact reviewed source from its commit alone. Public status
promotion should require clean reviewed source. Receipts are contributor statements,
not signed attestations; the challenge cannot prove who executed the command.

## Maintainer evidence workflow

1. Review contributor code first and identify the exact source commit.
2. If useful, request a fresh non-secret random challenge.
3. The contributor checks out that reviewed clean commit and runs locally using
   their own provider account and private credential entry.
4. Share only the sanitized receipt. The maintainer checks schema/invariants,
   commit, clean state, challenge, exact model, date, PASS and deterministic tests.
5. Change public evidence status only after accepting the actual receipt.

Creating this tool does not change existing provider evidence. Preserve dated
LIVE VERIFIED evidence for OpenAI/Gemini/Hugging Face, Ollama's incomplete local
evidence, and Anthropic's CONTRACT VERIFIED - LIVE VERIFICATION PENDING status
until acceptable new evidence is obtained. UNAVAILABLE describes one environment;
it is not an automatic public downgrade.

No live GitHub Actions workflow is added. Untrusted fork code must never receive
maintainer secrets. Any future live CI needs a separately protected,
approval-gated environment running reviewed source with minimal privileges,
bounded requests/spend and sanitized output.

## Deterministic checks

From packages/cache:

~~~text
uv run --no-sync --offline pytest tests/test_provider_live_verify.py tests/test_provider_adapters.py
uv run --no-sync --offline ruff check --config ../../ruff.toml ../../scripts/provider_live_verify.py ../../scripts/provider_live_verification tests/test_provider_live_verify.py
uv run --no-sync --offline mypy ../../scripts/provider_live_verify.py ../../scripts/provider_live_verification tests/test_provider_live_verify.py
~~~
