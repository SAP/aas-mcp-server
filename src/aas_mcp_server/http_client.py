# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
HTTP client configuration for AAS MCP Server.

This module builds the httpx.AsyncClient used by FastMCP's OpenAPIProvider
to call the AAS backend.

Authentication is handled automatically by FastMCP's OpenAPITool.run():
it calls get_http_headers() which forwards the inbound MCP request's
Authorization header (the validated OAuth Bearer token) to the AAS backend
at highest precedence. No static credentials are injected here.

For stdio transport, get_http_headers() returns an empty dict (no HTTP
request context), so the backend receives no Authorization header.
"""

import os
import httpx

from .constants import (
    ENV_AAS_HTTP_TIMEOUT,
    DEFAULT_HTTP_TIMEOUT,
)

# HTTP headers
HEADER_ACCEPT = "Accept"
HEADER_AUTHORIZATION = "Authorization"
CONTENT_TYPE_JSON = "application/json"

# Authorization format
AUTH_BEARER_FORMAT = "Bearer {token}"


def build_async_client(base_url: str) -> httpx.AsyncClient:
    """
    Build an async HTTP client with no static auth headers.

    Authentication is handled per-request by FastMCP's OpenAPITool.run(),
    which forwards the inbound Authorization header automatically via
    get_http_headers(). No credentials should be set here.

    Args:
        base_url: Base URL for the HTTP client

    Returns:
        Configured httpx.AsyncClient instance
    """
    headers = {HEADER_ACCEPT: CONTENT_TYPE_JSON}
    timeout = float(os.getenv(ENV_AAS_HTTP_TIMEOUT, str(DEFAULT_HTTP_TIMEOUT)))
    return httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout)
