import asyncio
from typing import cast

import pytest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.middleware.gateway_trace import GatewayTraceMiddleware


@pytest.mark.asyncio
async def test_trace_correlates_completed_and_cancelled_requests(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def completed(_scope: Scope, _receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def cancelled(_scope: Scope, _receive: Receive, _send: Send) -> None:
        raise asyncio.CancelledError

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message: Message) -> None:
        pass

    scope = cast(
        Scope,
        {
            "type": "http",
            "path": "/api/v1/query",
            "headers": [(b"x-request-id", b"0123456789abcdef0123456789abcdef")],
        },
    )
    with caplog.at_level("INFO", logger="app.middleware.gateway_trace"):
        await GatewayTraceMiddleware(cast(ASGIApp, completed))(scope, receive, send)
        with pytest.raises(asyncio.CancelledError):
            await GatewayTraceMiddleware(cast(ASGIApp, cancelled))(scope, receive, send)
        scope["headers"] = [(b"x-request-id", b"bad\nsecret")]
        await GatewayTraceMiddleware(cast(ASGIApp, completed))(scope, receive, send)

    assert (
        "rid=0123456789abcdef0123456789abcdef status=200 complete=True outcome=returned"
        in caplog.text
    )
    assert (
        "rid=0123456789abcdef0123456789abcdef status=0 complete=False outcome=cancelled"
        in caplog.text
    )
    assert "rid=- status=200 complete=True outcome=returned" in caplog.text
    assert "secret" not in caplog.text
