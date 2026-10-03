from enum import Enum


# The frozen public enum preserves str/Enum behavior, including str(member).
class CachePolicy(str, Enum):  # noqa: UP042
    NORMAL = "normal"
    READ_ONLY = "read_only"
    REFRESH = "refresh"
    BYPASS = "bypass"
    PRIVATE = "private"

    @property
    def _read_enabled(self) -> bool:
        return self in (CachePolicy.NORMAL, CachePolicy.READ_ONLY)

    @property
    def _write_enabled(self) -> bool:
        return self in (CachePolicy.NORMAL, CachePolicy.REFRESH)
