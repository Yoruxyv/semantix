"""Opt-in request lifecycle trace for gateway reset investigations."""

import asyncio
import logging
import re

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class GatewayTraceMiddleware:
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
