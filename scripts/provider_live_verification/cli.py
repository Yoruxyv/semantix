"""Local CLI, private credential entry, source inspection and safe output."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import shutil
import subprocess
import sys
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Never, cast

from typing_extensions import override

from .models import DEFAULT_TIMEOUT, Options, Provider, Receipt, SafeInputError, Source
from .providers import DEFAULTS, ENV_KEYS
from .runner import run_smoke

ROOT = Path(__file__).resolve().parents[2]


class SafeParser(argparse.ArgumentParser):
    @override
    def error(self, message: str) -> Never:
        self.exit(
            2, "Invalid arguments. Use --help; credentials are not CLI options.\n"
        )


def parse_args(argv: Sequence[str] | None = None) -> Options:
    parser = SafeParser(
        description="Bounded first-party provider smoke; may incur provider charges."
    )
    parser.add_argument("provider", choices=tuple(DEFAULTS))
    parser.add_argument("--challenge")
    parser.add_argument(
        "--model", help="Exact generation model; required for Anthropic"
    )
    parser.add_argument("--embedding-model")
    parser.add_argument("--embedding-dimensions", type=int)
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Total seconds, including cleanup: 10-120",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        help="Lower HTTP budget (1-3); cannot raise the fixed ceiling",
    )
    parser.add_argument(
        "--use-env",
        action="store_true",
        help="Use the documented provider key variable instead of secure input",
    )
    args = parser.parse_args(argv)
    provider = cast(Provider, args.provider)
    model, embedding_model, dimensions = DEFAULTS[provider]
    if (
        (
            provider == "anthropic"
            and (
                args.model is None
                or args.embedding_model is not None
                or args.embedding_dimensions is not None
            )
        )
        or ((args.embedding_model is None) != (args.embedding_dimensions is None))
        or (provider == "ollama" and args.use_env)
    ):
        parser.error("Invalid configuration")
    selected_model = args.model if args.model is not None else model
    if selected_model is None:
        parser.error("An explicit model is required")
    try:
        options = Options(
            provider=provider,
            model=selected_model,
            embedding_model=args.embedding_model
            if args.embedding_model is not None
            else embedding_model,
            embedding_dimensions=args.embedding_dimensions
            if args.embedding_dimensions is not None
            else dimensions,
            challenge=args.challenge,
            timeout=args.timeout,
            max_attempts=args.max_attempts
            if args.max_attempts is not None
            else (1 if provider == "anthropic" else 3),
            model_overridden=args.model is not None,
            embedding_overridden=args.embedding_model is not None,
            use_env=args.use_env,
        )
        if provider == "anthropic" and options.max_attempts != 1:
            parser.error("Anthropic HTTP ceiling is one")
    except ValueError:
        parser.error("Invalid configuration")
    return options


def credential(options: Options) -> str:
    if options.provider == "ollama":
        return ""
    failure = False
    value = ""
    try:
        if options.use_env:
            value = os.environ.get(ENV_KEYS[options.provider], "")
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                value = getpass.getpass("Provider API key (local, hidden): ")
    except (EOFError, OSError, getpass.GetPassWarning):
        failure = True
    if failure or not value or not value.isascii() or any(c.isspace() for c in value):
        raise SafeInputError("Secure credential input unavailable or invalid")
    return value


def read_source() -> Source:
    failure = False
    values: list[str] = []
    git = shutil.which("git")
    if git is None:
        raise SafeInputError("Git is unavailable")
    try:
        for args in (
            ["rev-parse", "HEAD"],
            ["rev-parse", "--abbrev-ref", "HEAD"],
            ["status", "--porcelain"],
        ):
            completed = subprocess.run(  # noqa: S603 -- fixed Git metadata operations
                [git, "-C", str(ROOT), *args],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            values.append(completed.stdout.strip())
        return Source(
            semantix_commit=values[0], branch=values[1], source_dirty=bool(values[2])
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        failure = True
    if failure:
        raise SafeInputError("Cannot verify local source metadata")
    raise RuntimeError("Unreachable source metadata state")


def human_receipt(receipt: Receipt) -> str:
    return (
        f"{receipt.provider}: {receipt.result}; HTTP {receipt.http_attempts}/{receipt.max_http_attempts}; "
        f"embed={receipt.embedding_calls} generate={receipt.generation_calls} "
        f"write={receipt.cache_writes} hit={receipt.confirmed_hits}; "
        f"cleanup={receipt.cleanup_status}; tasks={receipt.remaining_async_tasks}\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_args(argv)
    logging_before = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    message = ""
    exit_code = 3
    try:
        source = read_source()
        key = credential(options)
        receipt = asyncio.run(run_smoke(options, key, source))
        sys.stdout.write(receipt.model_dump_json(indent=2) + "\n")
        sys.stderr.write(human_receipt(receipt))
        return {"PASS": 0, "FAIL": 1, "UNAVAILABLE": 2}[receipt.result]
    except SafeInputError:
        message, exit_code = (
            "Verifier input unavailable or unsafe; no receipt issued.\n",
            2,
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        message, exit_code = "Verification cancelled.\n", 130
    except Exception:  # noqa: BLE001 -- CLI secret boundary; defects never become provider FAIL receipts
        message = (
            "Verifier defect; no provider receipt issued. Run deterministic checks.\n"
        )
    finally:
        logging.disable(logging_before)
    sys.stderr.write(message)
    return exit_code
