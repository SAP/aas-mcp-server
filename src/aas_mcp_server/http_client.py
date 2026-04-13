"""
HTTP client configuration for AAS MCP Server.

This module provides functionality to build async HTTP clients with
optional authentication (Bearer token or API key) for communicating
with AAS backend services.
"""

import os
import httpx

# Environment variable names for authentication
ENV_VAR_AAS_TOKEN = "AAS_TOKEN"
ENV_VAR_AAS_API_KEY = "AAS_API_KEY"
ENV_VAR_AAS_API_KEY_HEADER = "AAS_API_KEY_HEADER"
ENV_VAR_AAS_HTTP_TIMEOUT = "AAS_HTTP_TIMEOUT"

# Default values
DEFAULT_API_KEY_HEADER = "X-API-Key"
DEFAULT_HTTP_TIMEOUT = "30"

# HTTP headers
HEADER_ACCEPT = "Accept"
HEADER_AUTHORIZATION = "Authorization"
CONTENT_TYPE_JSON = "application/json"

# Authorization format
AUTH_BEARER_FORMAT = "Bearer {token}"


def build_async_client(base_url: str) -> httpx.AsyncClient:
    """
    Build an async HTTP client with optional authentication.

    Args:
        base_url: Base URL for the HTTP client

    Returns:
        Configured httpx.AsyncClient instance
    """
    token = os.getenv(ENV_VAR_AAS_TOKEN)  # optional bearer token
    api_key = os.getenv(ENV_VAR_AAS_API_KEY)  # optional API key
    api_key_header = os.getenv(ENV_VAR_AAS_API_KEY_HEADER, DEFAULT_API_KEY_HEADER)

    headers = {HEADER_ACCEPT: CONTENT_TYPE_JSON}

    if token:
        headers[HEADER_AUTHORIZATION] = AUTH_BEARER_FORMAT.format(token=token)
    if api_key:
        headers[api_key_header] = api_key

    timeout = float(os.getenv(ENV_VAR_AAS_HTTP_TIMEOUT, DEFAULT_HTTP_TIMEOUT))
    return httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout)
