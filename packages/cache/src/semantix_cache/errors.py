"""Safe embedded errors; custom integration programming errors propagate unchanged."""


class SemantixCacheError(Exception):
    """Base for documented embedded failures."""


class CacheConfigurationError(SemantixCacheError):
    """Invalid constructor configuration."""


class CacheValidationError(SemantixCacheError):
    """Invalid operation input."""


class EmbeddingError(SemantixCacheError):
    """Invalid embedding output or expected adapter failure."""


class EmbeddingSpaceError(EmbeddingError):
    """Incompatible or changed embedding metadata."""


class GenerationError(SemantixCacheError):
    """Invalid completed generation output."""


class CacheStoreError(SemantixCacheError):
    """Storage failure or malformed store result."""


class CacheTimeoutError(SemantixCacheError):
    """The operation's total deadline expired."""


class CacheClosedError(SemantixCacheError):
    """An operation used a closed resource."""


class CacheBusyError(SemantixCacheError):
    """Close requires admitted operations and workers to finish."""
