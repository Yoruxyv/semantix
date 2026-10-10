"""Opt-in request lifecycle trace for gateway reset investigations."""

import asyncio
import logging
import re

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class GatewayTraceMiddleware:
    """Log start/end evidence for opted-in HTTP /api/v1/query requests only.

    Accept the first supplied request ID only as 32 ASCII lowercase hex bytes;
    otherwise log "-". It is correlation text, not authenticated or guaranteed
    unique/server-generated. Logs contain ID, status, completion and outcome, not
    request bodies or exception messages.

    Update status/final-body completion only after the wrapped send succeeds.
    Defaults are status=0, complete=False, outcome=returned. CancelledError sets
    cancelled; ordinary Exception sets exception; both re-raise and log end in
    finally. Other BaseException values are not explicitly classified. Completion
    does not prove client receipt, every disconnect or provider fault diagnosis.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != "/api/v1/query":
            await self.app(scope, receive, send)
            return

        supplied_id = next(
            (
                value
                for name, value in scope["headers"]
                if name.lower() == b"x-request-id"
            ),
            b"",
        )
        request_id = (
            supplied_id.decode("ascii")
            if re.fullmatch(rb"[0-9a-f]{32}", supplied_id)
            else "-"
        )
        status = 0
        complete = False
        outcome = "returned"

        async def traced_send(message: Message) -> None:
            nonlocal status, complete
            await send(message)
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                complete = True

        logger.info("gateway trace start rid=%s", request_id)
        try:
            await self.app(scope, receive, traced_send)
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        except Exception:
            outcome = "exception"
            raise
        finally:
            logger.info(
                "gateway trace end rid=%s status=%s complete=%s outcome=%s",
                request_id,
                status,
                complete,
                outcome,
            )
