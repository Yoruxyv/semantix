"""Configure process logging with JSON output and known-secret substitution.

Callers supply the secret substrings. Only formatted message/exception paths are
redacted; this is not universal privacy protection for arbitrary loggers or data.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Final

from typing_extensions import override

_UVICORN_LOGGER_NAMES: Final = ("uvicorn", "uvicorn.error", "uvicorn.access")


class RedactingJsonFormatter(logging.Formatter):
    """Render JSON with sequential literal replacement of configured secrets.

    Ignore empty secret strings and replace case-sensitive occurrences in rendered
    message and exception text with [REDACTED], in supplied order. Logger names and
    level labels are not redacted, and arbitrary LogRecord extras are not included.
    Unknown secrets, prompts/responses and output from other handlers remain the
    caller's responsibility.

    Args:
        secrets: Known credential substrings, retained for this formatter's lifetime.
    """

    def __init__(self, secrets: tuple[str, ...]) -> None:
        super().__init__()
        self._secrets: Final[tuple[str, ...]] = tuple(
            value for value in secrets if value
        )

    def _redact(self, value: str) -> str:
        for secret in self._secrets:
            value = value.replace(secret, "[REDACTED]")
        return value

    @override
    def format(self, record: logging.LogRecord) -> str:
        """Render current UTC time, level, logger and redacted message as one JSON string.

        The timestamp is formatting time, not record.created. When exc_info is present,
        include redacted formatException text. JSON uses ensure_ascii=False; this method
        returns text and does not choose a stream or emit it itself.

        Args:
            record: Log record whose message arguments are rendered by getMessage.

        Returns:
            Serialized JSON payload with optional exception text.
        """
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self._redact(record.getMessage()),
        }
        if record.exc_info is not None:
            payload["exception"] = self._redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str, secrets: tuple[str, ...]) -> None:
    """Install one root stderr handler and format existing Uvicorn handlers as JSON.

    Detach existing root handlers without closing them, then set the root level.
    Set HTTPX to WARNING. Reuse handlers on uvicorn, uvicorn.error and uvicorn.access
    with the same formatter, without changing their levels or propagation.
    Other handlers may emit outside this formatter's redaction boundary.

    Args:
        level: Root logging level accepted by logging.Logger.setLevel.
        secrets: Known nonempty substrings to replace in messages and exception text.

    Raises:
        ValueError: The supplied root logging level is not recognized.
    """
    formatter = RedactingJsonFormatter(secrets)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    logging.getLogger("httpx").setLevel(logging.WARNING)

    for logger_name in _UVICORN_LOGGER_NAMES:
        for uvicorn_handler in logging.getLogger(logger_name).handlers:
            uvicorn_handler.setFormatter(formatter)
