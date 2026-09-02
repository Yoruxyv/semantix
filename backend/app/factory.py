from collections.abc import Callable
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import (
    AppError,
    app_error_handler,
    http_error_handler,
    rate_limit_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.core.logging import configure_logging
from app.core.version import API_VERSION
from app.lifecycle import create_lifespan
from app.middleware.body_limit import (
    RequestBodyLimitMiddleware,
    RequestBodyTooLargeError,
    request_body_too_large_handler,
)
from app.middleware.rate_limit import limiter
from app.providers.factory import create_default_provider_registry
from app.providers.registry import ProviderRegistry
from app.security.auth_attempts import AuthenticationAttemptTracker

API_TITLE = "Semantic Cache API"
CORS_ALLOWED_METHODS = ("GET", "POST", "PUT", "DELETE")
CORS_ALLOWED_HEADERS = ("Authorization", "Content-Type")


def create_app(
    settings: Settings | None = None,
    *,
    auth_attempt_clock: Callable[[], float] | None = None,
    provider_registry: ProviderRegistry | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_registry = provider_registry or create_default_provider_registry(
        resolved_settings
    )
    provider_selection = resolved_registry.resolve(
        resolved_settings.embedding_provider,
        resolved_settings.generation_provider,
    )
    logging_secrets = (
        resolved_settings.configured_secrets() + resolved_registry.configured_secrets()
    )

    configure_logging(
        resolved_settings.log_level,
        logging_secrets,
    )

    application = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        lifespan=create_lifespan(
            resolved_settings,
            provider_selection,
            logging_secrets=logging_secrets,
        ),
    )
    application.state.settings = resolved_settings
    application.state.rate_limit_scope = uuid4().hex
    application.state.authentication_attempt_tracker = (
        AuthenticationAttemptTracker()
        if auth_attempt_clock is None
        else AuthenticationAttemptTracker(clock=auth_attempt_clock)
    )

    _configure_middleware(application, resolved_settings)
    _register_exception_handlers(application)

    application.state.limiter = limiter
    application.state.embedding_provider_name = provider_selection.embedding_name
    application.state.generation_provider_name = provider_selection.generation_name
    application.include_router(api_router)

    return application


def _configure_middleware(application: FastAPI, settings: Settings) -> None:
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=CORS_ALLOWED_METHODS,
        allow_headers=CORS_ALLOWED_HEADERS,
    )
    application.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=settings.max_request_body_bytes,
    )


def _register_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(
        RequestBodyTooLargeError,
        request_body_too_large_handler,
    )
    application.add_exception_handler(AppError, app_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(RateLimitExceeded, rate_limit_error_handler)
    application.add_exception_handler(HTTPException, http_error_handler)
    application.add_exception_handler(Exception, unhandled_error_handler)
