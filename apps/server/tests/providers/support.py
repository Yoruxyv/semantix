from collections.abc import Callable

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_none,
)

from app.core.exceptions import ProviderRetryableError

MockHandler = Callable[
    [httpx.Request],
    httpx.Response,
]


def mock_client(handler: MockHandler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    )


def no_wait_retrying() -> AsyncRetrying:
    return AsyncRetrying(
        retry=retry_if_exception_type(ProviderRetryableError),
        stop=stop_after_attempt(3),
        wait=wait_none(),
        reraise=True,
    )
