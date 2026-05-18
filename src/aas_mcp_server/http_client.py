# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
HTTP client configuration for AAS MCP Server.

Authentication uses a custom httpx.Auth subclass (BearerTokenAuth) that reads
the validated OAuth access token from FastMCP's request context via
get_access_token() on every outbound request. This works correctly across all
FastMCP versions because it does not rely on get_http_headers(), which in
FastMCP >=3.3 explicitly excludes the Authorization header from forwarding.

For stdio transport (or when OAuth is not configured), get_access_token()
returns None and no Authorization header is added.
"""

import os
from typing import Generator

import httpx
from fastmcp.server.dependencies import get_access_token

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


class BearerTokenAuth(httpx.Auth):
    """
    httpx.Auth implementation that injects the current request's OAuth Bearer
    token into every outbound AAS backend call.

    Reads the token from FastMCP's get_access_token() at request time, so each
    tool invocation uses the token belonging to that specific MCP session user.
    Returns no Authorization header on stdio transport or when OAuth is not
    configured (get_access_token() returns None in those cases).
    """

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        access_token = get_access_token()
        if access_token is not None:
            request.headers[HEADER_AUTHORIZATION] = AUTH_BEARER_FORMAT.format(
                token=access_token.token
            )
        yield request


def build_async_client(base_url: str) -> httpx.AsyncClient:
    """
    Build an async HTTP client that forwards the OAuth Bearer token
    per-request via BearerTokenAuth.

    Args:
        base_url: Base URL for the AAS backend

    Returns:
        Configured httpx.AsyncClient instance
    """
    timeout = float(os.getenv(ENV_AAS_HTTP_TIMEOUT, str(DEFAULT_HTTP_TIMEOUT)))
    return httpx.AsyncClient(
        base_url=base_url,
        headers={HEADER_ACCEPT: CONTENT_TYPE_JSON},
        auth=BearerTokenAuth(),
        timeout=timeout,
    )
