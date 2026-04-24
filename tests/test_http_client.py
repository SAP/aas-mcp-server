# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for http_client module.

Tests the HTTP client builder with various authentication configurations.
"""

import os
from unittest.mock import patch

import httpx

from aas_mcp_server.http_client import (
    build_async_client,
    ENV_AAS_TOKEN,
    ENV_AAS_API_KEY,
    ENV_AAS_API_KEY_HEADER,
    ENV_AAS_HTTP_TIMEOUT,
    DEFAULT_API_KEY_HEADER,
    DEFAULT_HTTP_TIMEOUT,
    HEADER_ACCEPT,
    HEADER_AUTHORIZATION,
    CONTENT_TYPE_JSON,
    AUTH_BEARER_FORMAT,
)


class TestBuildAsyncClient:
    """Tests for build_async_client function."""

    def test_builds_client_with_base_url(self):
        """Test that client is built with correct base URL."""
        base_url = "http://localhost:8080"
        client = build_async_client(base_url)

        assert isinstance(client, httpx.AsyncClient)
        # httpx automatically adds trailing slash if not present
        assert str(client.base_url).rstrip("/") == base_url

    def test_sets_default_accept_header(self):
        """Test that Accept header is set to application/json."""
        client = build_async_client("http://localhost:8080")

        assert HEADER_ACCEPT in client.headers
        assert client.headers[HEADER_ACCEPT] == CONTENT_TYPE_JSON

    @patch.dict(os.environ, {ENV_AAS_TOKEN: "test-token-123"})
    def test_adds_bearer_token_when_env_var_set(self):
        """Test that Bearer token is added when AAS_TOKEN is set."""
        client = build_async_client("http://localhost:8080")

        assert HEADER_AUTHORIZATION in client.headers
        expected = AUTH_BEARER_FORMAT.format(token="test-token-123")
        assert client.headers[HEADER_AUTHORIZATION] == expected

    @patch.dict(os.environ, {}, clear=True)
    def test_no_authorization_header_without_token(self):
        """Test that Authorization header is not set without token."""
        client = build_async_client("http://localhost:8080")

        assert HEADER_AUTHORIZATION not in client.headers

    @patch.dict(os.environ, {ENV_AAS_API_KEY: "test-api-key-456"})
    def test_adds_api_key_with_default_header_name(self):
        """Test that API key is added with default header name."""
        client = build_async_client("http://localhost:8080")

        assert DEFAULT_API_KEY_HEADER in client.headers
        assert client.headers[DEFAULT_API_KEY_HEADER] == "test-api-key-456"

    @patch.dict(
        os.environ,
        {
            ENV_AAS_API_KEY: "test-api-key-789",
            ENV_AAS_API_KEY_HEADER: "X-Custom-API-Key",
        },
    )
    def test_adds_api_key_with_custom_header_name(self):
        """Test that API key is added with custom header name."""
        client = build_async_client("http://localhost:8080")

        assert "X-Custom-API-Key" in client.headers
        assert client.headers["X-Custom-API-Key"] == "test-api-key-789"

    @patch.dict(
        os.environ,
        {
            ENV_AAS_TOKEN: "token-abc",
            ENV_AAS_API_KEY: "key-xyz",
        },
    )
    def test_includes_both_token_and_api_key_when_both_set(self):
        """Test that both token and API key are included when both are set."""
        client = build_async_client("http://localhost:8080")

        assert HEADER_AUTHORIZATION in client.headers
        assert DEFAULT_API_KEY_HEADER in client.headers

    @patch.dict(os.environ, {ENV_AAS_HTTP_TIMEOUT: "60.5"})
    def test_uses_custom_timeout_from_env(self):
        """Test that custom timeout is used when env var is set."""
        client = build_async_client("http://localhost:8080")

        assert client.timeout.read == 60.5

    @patch.dict(os.environ, {}, clear=True)
    def test_uses_default_timeout_when_env_not_set(self):
        """Test that default timeout is used when env var is not set."""
        client = build_async_client("http://localhost:8080")

        expected_timeout = float(DEFAULT_HTTP_TIMEOUT)
        assert client.timeout.read == expected_timeout

    def test_client_is_async_client_instance(self):
        """Test that returned client is an AsyncClient instance."""
        client = build_async_client("http://localhost:8080")

        assert isinstance(client, httpx.AsyncClient)

    @patch.dict(os.environ, {}, clear=True)
    def test_headers_only_include_accept_when_no_auth(self):
        """Test that only Accept header is present without authentication."""
        client = build_async_client("http://localhost:8080")

        # Should only have Accept header, no auth headers
        assert HEADER_ACCEPT in client.headers
        assert HEADER_AUTHORIZATION not in client.headers
        assert DEFAULT_API_KEY_HEADER not in client.headers


class TestConstants:
    """Tests for module constants."""

    def test_default_api_key_header_is_correct(self):
        """Test that default API key header name is correct."""
        assert DEFAULT_API_KEY_HEADER == "X-API-Key"

    def test_default_timeout_is_string(self):
        """Test that default timeout is a string (for env var)."""
        assert isinstance(DEFAULT_HTTP_TIMEOUT, int)
        assert DEFAULT_HTTP_TIMEOUT == 30

    def test_content_type_json_is_correct(self):
        """Test that JSON content type is correct."""
        assert CONTENT_TYPE_JSON == "application/json"

    def test_auth_bearer_format_has_placeholder(self):
        """Test that bearer format has token placeholder."""
        assert "{token}" in AUTH_BEARER_FORMAT
        assert AUTH_BEARER_FORMAT.startswith("Bearer ")
