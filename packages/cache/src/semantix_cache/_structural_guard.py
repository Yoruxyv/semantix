"""Bounded prompt-pair feature; no answer validation or learned threshold."""

import re
from dataclasses import dataclass
from typing import Literal

IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]{0,63}"

Status = Literal["CONFLICT", "NO_CONFLICT_DETECTED", "UNSUPPORTED"]


@dataclass(frozen=True)
class Result:
    status: Status
    reason: str


def _task(prompt: str) -> tuple[str, tuple[str, ...]] | None:
    # Only complete explicit task grammars; escaped literals need separate semantics.
    for pattern in (
        rf"Copy (?:the )?identifier ({IDENTIFIER}) exactly\.",
        rf"Give the flag name ({IDENTIFIER}) exactly\.",
        rf"Return the exact flag name ({IDENTIFIER})\.",
    ):
        if match := re.fullmatch(pattern, prompt):
            return "identifier", (match[1],)
    for kind, pattern in (
        (
            "literal-copy",
            r'Copy (?:the )?literal string "([^"\\\r\n]{0,256})" exactly\. Return only the copied characters\.',
        ),
        (
            "utf8-bytes",
            r"Give (?:the )?UTF-8 hex bytes for '([^'\\\r\n]{0,256})'\.",
        ),
        (
            "unicode-codepoints",
            r"Give (?:the )?Unicode code points for '([^'\\\r\n]{0,256})'\.",
        ),
    ):
        if match := re.fullmatch(pattern, prompt):
            return kind, (match[1],)
    for pattern in (
        r"By exact character comparison, does literal '([^'\\\r\n]{0,256})' equal '([^'\\\r\n]{0,256})'\?",
        r"Does literal '([^'\\\r\n]{0,256})' equal '([^'\\\r\n]{0,256})' by exact character comparison\?",
    ):
        if match := re.fullmatch(pattern, prompt):
            return "literal-equality", (match[1], match[2])
    return None


def check(incoming: object, cached_prompt: object) -> Result:
    """Compare task-bound constraints only; a no-conflict result proves no answer."""
    if not isinstance(incoming, str) or not isinstance(cached_prompt, str):
        raise TypeError("Both prompts must be text")
    for prompt in (incoming, cached_prompt):
        if len(prompt) > 2000 or re.search(r"[\ud800-\udfff]", prompt):
            return Result("UNSUPPORTED", "Prompt bound or invalid Unicode scalar")
    left, right = _task(incoming), _task(cached_prompt)
    if left is None or right is None or left[0] != right[0]:
        return Result("UNSUPPORTED", "Unsupported or different task grammars")
    if left[1] == right[1]:
        return Result(
            "NO_CONFLICT_DETECTED", "Same supported task and exact literal values"
        )
    if left[0] == "literal-equality":
        if (left[1][0] == left[1][1]) == (right[1][0] == right[1][1]):
            return Result(
                "UNSUPPORTED",
                "Different comparison literals with the same truth value; explanations may not transfer",
            )
        return Result("CONFLICT", "Exact literal equality result changes")
    return Result(
        "CONFLICT", "Exact identifier, copied characters or encoding input changes"
    )
