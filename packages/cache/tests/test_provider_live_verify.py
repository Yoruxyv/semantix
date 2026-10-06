"""Deterministic verifier evidence and secret boundaries; never use live transports."""

import asyncio
import importlib.util
import json
import sys
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from semantix_cache import CacheStoreError
from tests.test_provider_adapters import embedding_payload, generation_payload

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "provider_live_verification",
    ROOT / "scripts/provider_live_verification/__init__.py",
)
assert SPEC is not None
assert SPEC.loader is not None
package = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = package
SPEC.loader.exec_module(package)
cli = importlib.import_module("provider_live_verification.cli")
models = importlib.import_module("provider_live_verification.models")
providers = importlib.import_module("provider_live_verification.providers")
runner = importlib.import_module("provider_live_verification.runner")
FAKE_CREDENTIAL = "fixture-credential-no-access"
ANSWER = "fixture-generated-answer-not-for-receipts"
PRIVATE = "fixture-private-provider-body"
PROVIDERS = tuple(providers.DEFAULTS)


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("A deterministic verifier test attempted live transport")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", forbidden)


def options(provider: str = "openai", *args: str) -> Any:
    model = ("--model", "fixture-model") if provider == "anthropic" else ()
    return cli.parse_args([provider, *model, *args])


def source() -> Any:
    return models.Source(
        semantix_commit="1" * 40, branch="test/verifier", source_dirty=False
    )


def handler(
    config: Any, requests: list[httpx.Request]
) -> Callable[[httpx.Request], httpx.Response]:
    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        embedding = request.url.path.endswith(
            (
                "/embeddings",
                ":embedContent",
                "/api/embed",
                "/pipeline/feature-extraction",
            )
        )
        payload = (
            embedding_payload(
                config.provider, [1.0] + [0.0] * (config.embedding_dimensions - 1)
            )
            if embedding
            else generation_payload(config.provider, ANSWER)
        )
        return httpx.Response(200, json=payload)

    return respond


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_public_cache_flow_and_observed_counters(provider: str) -> None:
    config = options(provider, "--challenge", "semantix-review-a1b2")
    requests: list[httpx.Request] = []
    receipt = await runner.run_smoke(
        config,
        FAKE_CREDENTIAL,
        source(),
        transport=httpx.MockTransport(handler(config, requests)),
    )
    expected = 1 if provider == "anthropic" else 3
    assert receipt.result == "PASS"
    assert receipt.challenge == "semantix-review-a1b2"
    assert receipt.http_attempts == len(requests) == expected
    assert (receipt.embedding_calls, receipt.generation_calls) == (2, 1)
    assert (receipt.cache_writes, receipt.confirmed_hits) == (1, 1)
    assert receipt.first_resolve_miss
    assert receipt.second_generation_skipped
    assert receipt.response_equal
    assert receipt.ownership_verified
    assert receipt.cleanup_status == "complete"
    assert receipt.remaining_async_tasks == receipt.retry_count == 0
    assert receipt.embedding_source == (
        "deterministic-local" if provider == "anthropic" else "first-party"
    )
    assert receipt.api_source == (
        "local-first-party" if provider == "ollama" else "first-party"
    )
    assert receipt.adapter_path == f"semantix_cache.adapters.{provider}"
    assert all(
        (
            r.url.scheme,
            r.url.host,
            r.url.port or (443 if r.url.scheme == "https" else 80),
        )
        == providers.ORIGINS[provider]
        for r in requests
    )
    serialized = receipt.model_dump_json()
    assert models.Receipt.model_validate_json(serialized) == receipt
    assert ANSWER not in serialized
    assert FAKE_CREDENTIAL not in serialized
    assert runner.PROMPT not in serialized
    assert "PASS" in cli.human_receipt(receipt)


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["unknown"],
        ["openai", "--api-key", FAKE_CREDENTIAL],
        ["openai", "--timeout", "nan"],
        ["openai", "--timeout", "inf"],
        ["openai", "--timeout", "9.9"],
        ["openai", "--timeout", "120.1"],
        ["openai", "--max-attempts", "0"],
        ["openai", "--max-attempts", "4"],
        ["anthropic"],
        ["anthropic", "--model", "fixture", "--max-attempts", "2"],
        ["anthropic", "--model", "fixture", "--embedding-model", "another"],
        ["openai", "--model", ""],
        ["openai", "--model", " https://private.example "],
        ["openai", "--embedding-model", "another"],
        ["openai", "--embedding-dimensions", "384"],
        ["openai", "--embedding-model", "another", "--embedding-dimensions", "0"],
        ["openai", "--challenge", "x\nprivate"],
        ["openai", "--challenge", "x" * 129],
        ["ollama", "--use-env"],
    ],
)
def test_cli_rejects_invalid_input_without_echo(
    arguments: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.parse_args(arguments)
    assert caught.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert FAKE_CREDENTIAL not in output.err
    assert "private.example" not in output.err
    assert "Invalid arguments" in output.err


@pytest.mark.parametrize("timeout", ["10", "60", "120"])
def test_cli_defaults_and_explicit_overrides(timeout: str) -> None:
    config = options(
        "openai",
        "--model",
        "fixture-exact-model",
        "--embedding-model",
        "fixture-embed",
        "--embedding-dimensions",
        "2",
        "--timeout",
        timeout,
    )
    assert config.model == "fixture-exact-model"
    assert config.embedding_model == "fixture-embed"
    assert config.embedding_dimensions == 2
    assert config.model_overridden
    assert config.embedding_overridden
    assert config.timeout == pytest.approx(float(timeout))
    assert config.max_attempts == 3
    assert config.challenge is None
    assert not config.use_env


def test_receipt_schema_is_generated_from_authoritative_model() -> None:
    schema = json.loads(
        (ROOT / "scripts/provider_live_receipt.schema.json").read_text()
    )
    assert schema == models.Receipt.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "1.0.0"


@pytest.mark.parametrize(
    "field",
    [
        "api_key",
        "Authorization",
        "headers",
        "raw_response",
        "answer",
        "account_id",
        "project_id",
        "billing",
        "environment",
        "cookies",
        "tokens",
    ],
)
async def test_receipt_rejects_unexpected_secret_fields(field: str) -> None:
    config = options("anthropic")
    receipt = await runner.run_smoke(
        config,
        FAKE_CREDENTIAL,
        source(),
        transport=httpx.MockTransport(handler(config, [])),
    )
    payload = receipt.model_dump()
    payload[field] = FAKE_CREDENTIAL
    with pytest.raises(ValidationError) as caught:
        models.Receipt.model_validate(payload)
    assert FAKE_CREDENTIAL not in str(caught.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("generation_calls", 2),
        ("cache_writes", 0),
        ("confirmed_hits", 0),
        ("embedding_calls", 1),
        ("http_attempts", 0),
        ("response_equal", False),
        ("first_resolve_miss", False),
        ("second_generation_skipped", False),
        ("ownership_verified", False),
        ("remaining_async_tasks", 1),
        ("cleanup_status", "failed"),
        ("http_status_category", "client_error"),
        ("adapter_path", "gateway"),
        ("api_source", "local-first-party"),
        ("failure_category", "provider_error"),
        ("retry_count", 1),
    ],
)
async def test_pass_cannot_be_fabricated(field: str, value: object) -> None:
    config = options("anthropic")
    receipt = await runner.run_smoke(
        config,
        FAKE_CREDENTIAL,
        source(),
        transport=httpx.MockTransport(handler(config, [])),
    )
    payload = receipt.model_dump()
    payload[field] = value
    with pytest.raises(ValidationError):
        models.Receipt.model_validate(payload)


@pytest.mark.parametrize("status", [302, 400, 401, 404, 429, 503])
@pytest.mark.parametrize("provider", ["openai", "ollama"])
async def test_status_failure_is_sanitized_and_not_retried(
    provider: str,
    status: int,
) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            status,
            text=FAKE_CREDENTIAL + PRIVATE,
            headers={"Location": "https://private.example", "x-account": PRIVATE},
        )

    receipt = await runner.run_smoke(
        options(provider),
        FAKE_CREDENTIAL,
        source(),
        transport=httpx.MockTransport(respond),
    )
    assert receipt.result == (
        "UNAVAILABLE" if provider == "ollama" and status == 404 else "FAIL"
    )
    assert receipt.http_attempts == calls == 1
    assert receipt.embedding_calls == 1
    assert (
        receipt.generation_calls == receipt.cache_writes == receipt.confirmed_hits == 0
    )
    assert receipt.cleanup_status == "complete"
    assert receipt.remaining_async_tasks == 0
    assert FAKE_CREDENTIAL not in receipt.model_dump_json()
    assert PRIVATE not in receipt.model_dump_json()


@pytest.mark.parametrize(
    ("provider", "kind", "expected"),
    [
        ("ollama", "connect", "UNAVAILABLE"),
        ("openai", "connect", "FAIL"),
        ("ollama", "timeout", "FAIL"),
        ("openai", "timeout", "FAIL"),
    ],
)
async def test_transport_classification_and_cleanup(
    provider: str,
    kind: str,
    expected: str,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        error = httpx.ConnectError if kind == "connect" else httpx.ReadTimeout
        raise error(FAKE_CREDENTIAL + PRIVATE, request=request)

    receipt = await runner.run_smoke(
        options(provider),
        FAKE_CREDENTIAL,
        source(),
        transport=httpx.MockTransport(respond),
    )
    assert receipt.result == expected
    assert receipt.http_attempts == 1
    assert receipt.retry_count == 0
    assert receipt.http_status_category == (
        "transport_error" if kind == "connect" else "timeout"
    )
    assert receipt.cleanup_status == "complete"
    assert receipt.remaining_async_tasks == 0
    assert FAKE_CREDENTIAL not in receipt.model_dump_json()


@pytest.mark.parametrize("payload", [None, {}, [0.0, 0.0], [float("nan"), 0.0]])
async def test_invalid_embeddings_do_not_generate_or_write(payload: object) -> None:
    receipt = await runner.run_smoke(
        options(),
        FAKE_CREDENTIAL,
        source(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=json.dumps(embedding_payload("openai", payload))
            )
        ),
    )
    assert receipt.result == "FAIL"
    assert receipt.generation_calls == receipt.cache_writes == 0


async def test_late_generation_failure_has_truthful_partial_counters() -> None:
    config = options()
    requests: list[httpx.Request] = []
    good = handler(config, requests)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return good(request)
        requests.append(request)
        return httpx.Response(200, text=FAKE_CREDENTIAL + PRIVATE)

    receipt = await runner.run_smoke(
        config, FAKE_CREDENTIAL, source(), transport=httpx.MockTransport(respond)
    )
    assert receipt.result == "FAIL"
    assert (
        receipt.http_attempts,
        receipt.embedding_calls,
        receipt.generation_calls,
    ) == (2, 1, 1)
    assert receipt.cache_writes == receipt.confirmed_hits == 0


async def test_lower_attempt_budget_stops_before_dispatch() -> None:
    config = options("openai", "--max-attempts", "2")
    requests: list[httpx.Request] = []
    receipt = await runner.run_smoke(
        config,
        FAKE_CREDENTIAL,
        source(),
        transport=httpx.MockTransport(handler(config, requests)),
    )
    assert receipt.result == "FAIL"
    assert receipt.http_status_category == "attempt_limit"
    assert receipt.http_attempts == len(requests) == 2
    assert receipt.embedding_calls == 2
    assert receipt.generation_calls == receipt.cache_writes == 1
    assert receipt.confirmed_hits == 0


async def test_failed_persistence_is_not_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failed(self: object, entry: object, **kwargs: object) -> None:
        raise CacheStoreError("fixture store failure")

    monkeypatch.setattr(runner.CountedStore, "put", failed)
    config = options("anthropic")
    receipt = await runner.run_smoke(
        config,
        FAKE_CREDENTIAL,
        source(),
        transport=httpx.MockTransport(handler(config, [])),
    )
    assert receipt.result == "FAIL"
    assert receipt.generation_calls == 1
    assert receipt.cache_writes == 0


async def test_unconfirmed_match_cannot_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    async def reject(self: object, key: str, **kwargs: object) -> bool:
        return False

    monkeypatch.setattr(runner.CountedStore, "record_hit", reject)
    config = options("anthropic")
    requests: list[httpx.Request] = []
    receipt = await runner.run_smoke(
        config,
        FAKE_CREDENTIAL,
        source(),
        transport=httpx.MockTransport(handler(config, requests)),
    )
    assert receipt.result == "FAIL"
    assert receipt.confirmed_hits == 0
    assert receipt.generation_calls == 2
    assert len(requests) == 1


async def test_cancellation_propagates_and_closes_owned_transport() -> None:
    started = asyncio.Event()

    class Blocking(httpx.AsyncBaseTransport):
        closed = False

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("Cancelled request resumed")

        async def aclose(self) -> None:
            self.closed = True

    transport = Blocking()
    baseline = asyncio.all_tasks()
    task = asyncio.create_task(
        runner.run_smoke(
            options("anthropic"), FAKE_CREDENTIAL, source(), transport=transport
        )
    )
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert transport.closed
    assert not asyncio.all_tasks() - baseline


async def test_cleanup_failure_is_not_pass() -> None:
    config = options("anthropic")

    class BrokenClose(httpx.MockTransport):
        async def aclose(self) -> None:
            raise httpx.NetworkError(FAKE_CREDENTIAL + PRIVATE)

    receipt = await runner.run_smoke(
        config, FAKE_CREDENTIAL, source(), transport=BrokenClose(handler(config, []))
    )
    assert receipt.result == "FAIL"
    assert receipt.cleanup_status == "failed"
    assert receipt.failure_category == "cleanup"


async def test_leaked_task_is_visible_and_fails() -> None:
    config = options("anthropic")
    leaked: list[asyncio.Task[bool]] = []
    good = handler(config, [])

    def respond(request: httpx.Request) -> httpx.Response:
        leaked.append(asyncio.create_task(asyncio.Event().wait()))
        return good(request)

    try:
        receipt = await runner.run_smoke(
            config, FAKE_CREDENTIAL, source(), transport=httpx.MockTransport(respond)
        )
        assert receipt.result == "FAIL"
        assert receipt.failure_category == "task_leak"
        assert receipt.remaining_async_tasks == 1
    finally:
        for task in leaked:
            task.cancel()
        await asyncio.gather(*leaked, return_exceptions=True)


async def test_programming_defect_propagates_from_runner() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise ValueError("fixture-programming-defect")

    with pytest.raises(ValueError, match="fixture-programming-defect"):
        await runner.run_smoke(
            options("anthropic"),
            FAKE_CREDENTIAL,
            source(),
            transport=httpx.MockTransport(respond),
        )


@pytest.mark.parametrize("use_env", [True, False])
def test_private_credential_input(
    use_env: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_CREDENTIAL)
    calls: list[str] = []

    def secure(prompt: str) -> str:
        calls.append(prompt)
        return FAKE_CREDENTIAL

    monkeypatch.setattr(cli.getpass, "getpass", secure)
    config = options("openai", *(("--use-env",) if use_env else ()))
    assert cli.credential(config) == FAKE_CREDENTIAL
    assert len(calls) == (0 if use_env else 1)


def test_getpass_cannot_fall_back_to_echo(monkeypatch: pytest.MonkeyPatch) -> None:
    def insecure(prompt: str) -> str:
        warnings.warn("fixture warning", cli.getpass.GetPassWarning, stacklevel=2)
        raise AssertionError("Echo fallback continued")

    monkeypatch.setattr(cli.getpass, "getpass", insecure)
    with pytest.raises(models.SafeInputError):
        cli.credential(options())


@pytest.mark.parametrize("metadata", ["challenge", "model", "branch"])
async def test_known_credential_cannot_enter_metadata(metadata: str) -> None:
    config = options("anthropic")
    src = source()
    if metadata == "branch":
        src = src.model_copy(update={"branch": FAKE_CREDENTIAL})
    else:
        config = config.model_copy(update={metadata: FAKE_CREDENTIAL})
    with pytest.raises(models.SafeInputError) as caught:
        await runner.run_smoke(config, FAKE_CREDENTIAL, src)
    assert FAKE_CREDENTIAL not in str(caught.value)


def test_cli_outputs_only_safe_receipt_and_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = runner.run_smoke

    async def offline(config: Any, key: str, src: Any) -> Any:
        return await original(
            config, key, src, transport=httpx.MockTransport(handler(config, []))
        )

    monkeypatch.setattr(cli, "read_source", source)
    monkeypatch.setattr(cli, "run_smoke", offline)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: FAKE_CREDENTIAL)
    assert cli.main(["anthropic", "--model", "fixture-model"]) == 0
    output = capsys.readouterr()
    receipt = models.Receipt.model_validate_json(output.out)
    assert receipt.result == "PASS"
    for forbidden in (FAKE_CREDENTIAL, ANSWER, PRIVATE, runner.PROMPT):
        assert forbidden not in output.out + output.err
    assert "anthropic: PASS" in output.err


def test_cli_defect_is_sanitized_without_false_provider_receipt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def bug(*args: object, **kwargs: object) -> None:
        raise ValueError(FAKE_CREDENTIAL + PRIVATE)

    monkeypatch.setattr(cli, "read_source", source)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: FAKE_CREDENTIAL)
    monkeypatch.setattr(cli, "run_smoke", bug)
    assert cli.main(["anthropic", "--model", "fixture-model"]) == 3
    output = capsys.readouterr()
    assert output.out == ""
    assert "Verifier defect" in output.err
    assert FAKE_CREDENTIAL not in output.err
    assert PRIVATE not in output.err


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_overrides_and_token_cap_reach_maintained_adapters(provider: str) -> None:
    extra_args = (
        ()
        if provider == "anthropic"
        else ("--embedding-model", "fixture-embed", "--embedding-dimensions", "2")
    )
    config = options(provider, "--model", "fixture-model", *extra_args)
    requests: list[httpx.Request] = []
    receipt = await runner.run_smoke(
        config,
        FAKE_CREDENTIAL,
        source(),
        transport=httpx.MockTransport(handler(config, requests)),
    )
    assert receipt.result == "PASS"
    assert receipt.model == "fixture-model"
    assert receipt.model_overridden
    generation = json.loads(requests[0 if provider == "anthropic" else 1].content)
    if provider == "gemini":
        assert generation["generationConfig"]["maxOutputTokens"] == 64
        assert requests[1].url.path.endswith("/fixture-model:generateContent")
    else:
        assert generation["model"] == "fixture-model"
        if provider == "ollama":
            assert generation["options"]["num_predict"] == 64
        else:
            field = "max_completion_tokens" if provider == "openai" else "max_tokens"
            assert generation[field] == 64


@pytest.mark.parametrize(
    "credential_value", ['fixture-with-quote"-value', "fixture-with-backslash\\value"]
)
async def test_json_escaping_cannot_hide_credential(credential_value: str) -> None:
    config = options("anthropic", "--challenge", credential_value)
    with pytest.raises(models.SafeInputError):
        await runner.run_smoke(config, credential_value, source())


@pytest.mark.parametrize(
    ("provider", "status", "expected_code", "expected_result"),
    [("openai", 401, 1, "FAIL"), ("ollama", 404, 2, "UNAVAILABLE")],
)
def test_cli_failure_receipts_never_expose_environment_or_provider_data(
    provider: str,
    status: int,
    expected_code: int,
    expected_result: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = runner.run_smoke

    async def offline(config: Any, key: str, src: Any) -> Any:
        return await original(
            config,
            key,
            src,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, text=FAKE_CREDENTIAL + PRIVATE)
            ),
        )

    monkeypatch.setenv("OPENAI_API_KEY", FAKE_CREDENTIAL)
    monkeypatch.setattr(cli, "read_source", source)
    monkeypatch.setattr(cli, "run_smoke", offline)
    args = [provider, *(["--use-env"] if provider == "openai" else [])]
    assert cli.main(args) == expected_code
    output = capsys.readouterr()
    assert models.Receipt.model_validate_json(output.out).result == expected_result
    assert FAKE_CREDENTIAL not in output.out + output.err
    assert PRIVATE not in output.out + output.err


async def test_default_owned_transport_disables_retries_and_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = options("anthropic")
    captured: dict[str, Any] = {}
    closed: list[bool] = []

    class Owned(httpx.MockTransport):
        async def aclose(self) -> None:
            closed.append(True)

    def factory(**kwargs: Any) -> httpx.AsyncBaseTransport:
        captured.update(kwargs)
        return Owned(handler(config, []))

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", factory)
    receipt = await runner.run_smoke(config, FAKE_CREDENTIAL, source())
    assert receipt.result == "PASS"
    assert captured["retries"] == 0
    assert captured["trust_env"] is False
    assert captured["limits"].max_connections == 1
    assert closed == [True]


async def test_total_deadline_is_bounded_and_cleanup_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_timeout = asyncio.timeout

    def shortened(delay: float | None) -> asyncio.Timeout:
        return original_timeout(0.01 if delay is not None and delay > 50 else delay)

    monkeypatch.setattr(runner.asyncio, "timeout", shortened)

    class Slow(httpx.AsyncBaseTransport):
        closed = False

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            await asyncio.Event().wait()
            raise AssertionError("Deadline did not cancel request")

        async def aclose(self) -> None:
            self.closed = True

    transport = Slow()
    receipt = await runner.run_smoke(
        options("anthropic"),
        FAKE_CREDENTIAL,
        source(),
        transport=transport,
    )
    assert receipt.result == "FAIL"
    assert receipt.failure_category == "deadline"
    assert receipt.http_attempts == 1
    assert receipt.cleanup_status == "complete"
    assert receipt.remaining_async_tasks == 0
    assert transport.closed


def test_source_metadata_is_bounded_and_does_not_reveal_git_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []
    outputs = iter(["1" * 40, "feat/verifier", " M scripts/provider_live_verify.py"])

    def git(*args: object, **kwargs: Any) -> Any:
        seen.append(kwargs)
        return type("GitOutput", (), {"stdout": next(outputs)})()

    monkeypatch.setattr(cli.shutil, "which", lambda name: "/fixture/git")
    monkeypatch.setattr(cli.subprocess, "run", git)
    evidence = cli.read_source()
    assert evidence.source_dirty
    assert evidence.branch == "feat/verifier"
    assert len(seen) == 3
    assert all(call["timeout"] == 5 for call in seen)

    def failed(*args: object, **kwargs: object) -> None:
        raise OSError(FAKE_CREDENTIAL + PRIVATE)

    monkeypatch.setattr(cli.subprocess, "run", failed)
    with pytest.raises(models.SafeInputError) as caught:
        cli.read_source()
    assert FAKE_CREDENTIAL not in str(caught.value)
    assert caught.value.__context__ is None
