import json
import logging
from datetime import UTC, datetime
from typing import Final

_UVICORN_LOGGER_NAMES: Final = ("uvicorn", "uvicorn.error", "uvicorn.access")


class RedactingJsonFormatter(logging.Formatter):
    def __init__(self, secrets: tuple[str, ...]) -> None:
        super().__init__()
        self._secrets: Final[tuple[str, ...]] = tuple(
            value for value in secrets if value
        )

    def _redact(self, value: str) -> str:
        for secret in self._secrets:
            value = value.replace(secret, "[REDACTED]")
        return value

    def format(self, record: logging.LogRecord) -> str:
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
