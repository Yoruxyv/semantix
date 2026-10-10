"""Enforce declared and downstream-consumed HTTP body-byte limits without buffering."""

import json
from typing import cast

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestBodyTooLargeError(HTTPException):
    """HTTP 413 error carrying request_too_large and the configured byte-limit detail."""

    error_code = "request_too_large"

    def __init__(self, max_body_bytes: int) -> None:
        super().__init__(
            status_code=413,
            detail=f"Request body exceeds the {max_body_bytes}-byte limit.",
        )


async def request_body_too_large_handler(
    _request: Request,
    exc: Exception,
) -> JSONResponse:
    """Render the registered RequestBodyTooLargeError as the established 413 JSON shape.

    The cast assumes the exception-handler registration supplies that error type;
    this handler is not an arbitrary-exception validator.
    """
    error = cast(RequestBodyTooLargeError, exc)
    return JSONResponse(
        status_code=error.status_code,
        content={"error": error.error_code, "detail": error.detail},
    )


class RequestBodyLimitMiddleware:
    """Check HTTP admission headers and count body chunks consumed by downstream code.

    Non-HTTP scopes pass through. The first Content-Length header is decoded as ASCII
    and parsed with int; invalid/negative values take the existing 400 path, while a
    value above the limit gets 413 before downstream handling. Duplicate headers are
    not reconciled and accepted length does not prove actual payload size.

    Missing or in-limit length still uses wrapped receive accounting. Only consumed
    http.request body bytes count; this does not pre-read, buffer or verify unread
    incoming bytes. Exact limit is allowed. Cancellation/other downstream errors
    propagate rather than becoming body-limit errors.

    Args:
        app: Borrowed downstream ASGI application.
        max_body_bytes: Configured limit supplied by validated application settings.
    """

    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self._app = app
        self._max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        declared_length = self._content_length(scope)
        if declared_length is None:
            await self._run_with_stream_limit(scope, receive, send)
            return
        if declared_length < 0:
            await self._send_error(
                send,
                400,
                "invalid_content_length",
                "Invalid Content-Length header.",
            )
            return
        if declared_length > self._max_body_bytes:
            await self._send_too_large(send)
            return
        await self._run_with_stream_limit(scope, receive, send)

    def _content_length(self, scope: Scope) -> int | None:
        for name, value in scope.get("headers", []):
            if name.lower() != b"content-length":
                continue
            try:
                return int(value.decode("ascii"))
            except ValueError:
                return -1
        return None

    async def _run_with_stream_limit(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Wrap receives and sends, substituting 413 only before response start.

        Raise RequestBodyTooLargeError before forwarding the chunk that crosses the
        limit. Mark response_started before forwarding http.response.start. If that
        error escapes downstream afterward, re-raise; headers cannot be replaced with
        a fresh 413. Downstream may handle the exception itself.
        """
        consumed = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self._max_body_bytes:
                    raise RequestBodyTooLargeError(self._max_body_bytes)
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, limited_receive, tracked_send)
        except RequestBodyTooLargeError:
            if response_started:
                raise
            await self._send_too_large(send)

    async def _send_too_large(self, send: Send) -> None:
        error = RequestBodyTooLargeError(self._max_body_bytes)
        await self._send_error(
            send,
            error.status_code,
            error.error_code,
            str(error.detail),
        )

    @staticmethod
    async def _send_error(
        send: Send,
        status_code: int,
        error: str,
        detail: str,
    ) -> None:
        body = json.dumps({"error": error, "detail": detail}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
