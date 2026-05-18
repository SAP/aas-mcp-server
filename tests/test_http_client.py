# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for http_client module.

Tests the HTTP client builder. Authentication is no longer static —
the inbound OAuth Bearer token is forwarded per-request by FastMCP's
OpenAPITool.run() via get_http_headers(). These tests confirm that
the client itself has no static auth headers.
"""

import os
from unittest.mock import patch

import httpx

from aas_mcp_server.http_client import (
    build_async_client,
    HEADER_ACCEPT,
    HEADER_AUTHORIZATION,
    CONTENT_TYPE_JSON,
    AUTH_BEARER_FORMAT,
)
from aas_mcp_server.constants import ENV_AAS_HTTP_TIMEOUT, DEFAULT_HTTP_TIMEOUT


# Test base URL reused across all client-builder tests
TEST_BASE_URL = "http://localhost:8080"


class TestBuildAsyncClient:
    """Tests for build_async_client function."""

    def test_builds_client_with_base_url(self):
        """Test that client is built with correct base URL."""
        base_url = TEST_BASE_URL
        client = build_async_client(base_url)

        assert isinstance(client, httpx.AsyncClient)
        assert str(client.base_url).rstrip("/") == base_url

    def test_sets_default_accept_header(self):
        """Test that Accept header is set to application/json."""
        client = build_async_client(TEST_BASE_URL)

        assert HEADER_ACCEPT in client.headers
        assert client.headers[HEADER_ACCEPT] == CONTENT_TYPE_JSON

    @patch.dict(os.environ, {}, clear=True)
    def test_no_authorization_header_in_client(self):
        """Client must NOT have a static Authorization header.

        Token injection is done per-request by FastMCP's OpenAPITool.run()
        via get_http_headers(), not by the client itself.
        """
        client = build_async_client(TEST_BASE_URL)

        assert HEADER_AUTHORIZATION not in client.headers

    @patch.dict(os.environ, {ENV_AAS_HTTP_TIMEOUT: "60.5"})
    def test_uses_custom_timeout_from_env(self):
        """Test that custom timeout is used when env var is set."""
        client = build_async_client(TEST_BASE_URL)

        assert client.timeout.read == 60.5

    @patch.dict(os.environ, {}, clear=True)
    def test_uses_default_timeout_when_env_not_set(self):
        """Test that default timeout is used when env var is not set."""
        client = build_async_client(TEST_BASE_URL)

        assert client.timeout.read == float(DEFAULT_HTTP_TIMEOUT)

    def test_client_is_async_client_instance(self):
        """Test that returned client is an AsyncClient instance."""
        assert isinstance(build_async_client(TEST_BASE_URL), httpx.AsyncClient)

    @patch.dict(os.environ, {}, clear=True)
    def test_headers_only_include_accept(self):
        """Only Accept header present — no static auth headers of any kind."""
        client = build_async_client(TEST_BASE_URL)

        assert HEADER_ACCEPT in client.headers
        assert HEADER_AUTHORIZATION not in client.headers
        # Legacy API key header must also be absent
        assert "X-API-Key" not in client.headers


class TestConstants:
    """Tests for module constants."""

    def test_default_timeout_value(self):
        assert DEFAULT_HTTP_TIMEOUT == 30

    def test_content_type_json(self):
        assert CONTENT_TYPE_JSON == "application/json"

    def test_auth_bearer_format(self):
        assert "{token}" in AUTH_BEARER_FORMAT
        assert AUTH_BEARER_FORMAT.startswith("Bearer ")
