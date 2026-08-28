# Semantix SDKs

This directory contains independently installable clients for the public
Semantix HTTP API. SDKs here are integration libraries, not embedded cache
engines, and they do not import server implementation modules.

## Available SDKs

| SDK | Package documentation |
|---|---|
| Python | [Python client](python/README.md) |

The Python package is the Phase 10 reference integration boundary. Future SDKs
should follow the same server-authoritative authentication, namespace, and cache
semantics instead of duplicating backend behavior locally.
