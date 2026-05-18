# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for http_client module.

Tests the HTTP client builder and BearerTokenAuth.

BearerTokenAuth reads get_access_token() from FastMCP's request context at
request time. Tests mock that function to verify the correct Authorization
header is injected when a token is present, and absent when there is none.
"""

import os
from unittest.mock import MagicMock, patch

import httpx

from aas_mcp_server.http_client import (
    BearerTokenAuth,
    build_async_client,
    HEADER_ACCEPT,
    HEADER_AUTHORIZATION,
    CONTENT_TYPE_JSON,
    AUTH_BEARER_FORMAT,
)
from aas_mcp_server.constants import ENV_AAS_HTTP_TIMEOUT, DEFAULT_HTTP_TIMEOUT


# Test base URL reused across all client-builder tests
TEST_BASE_URL = "http://localhost:8080"

# Token value used in auth tests
TEST_TOKEN = "test-bearer-token-abc123"


class TestBuildAsyncClient:
    """Tests for build_async_client function."""

    def test_builds_client_with_base_url(self):
        """Client is built with the correct base URL."""
        client = build_async_client(TEST_BASE_URL)
        assert isinstance(client, httpx.AsyncClient)
        assert str(client.base_url).rstrip("/") == TEST_BASE_URL

    def test_sets_default_accept_header(self):
        """Accept: application/json is set as a default header."""
        client = build_async_client(TEST_BASE_URL)
        assert HEADER_ACCEPT in client.headers
        assert client.headers[HEADER_ACCEPT] == CONTENT_TYPE_JSON

    @patch.dict(os.environ, {}, clear=True)
    def test_no_static_authorization_header(self):
        """No static Authorization header — auth is per-request via BearerTokenAuth."""
        client = build_async_client(TEST_BASE_URL)
        assert HEADER_AUTHORIZATION not in client.headers

    def test_uses_bearer_token_auth(self):
        """Client uses BearerTokenAuth for per-request token injection."""
        client = build_async_client(TEST_BASE_URL)
        assert isinstance(client.auth, BearerTokenAuth)

    @patch.dict(os.environ, {ENV_AAS_HTTP_TIMEOUT: "60.5"})
    def test_uses_custom_timeout_from_env(self):
        """Custom timeout is read from AAS_HTTP_TIMEOUT env var."""
        client = build_async_client(TEST_BASE_URL)
        assert client.timeout.read == 60.5

    @patch.dict(os.environ, {}, clear=True)
    def test_uses_default_timeout_when_env_not_set(self):
        """Default timeout is used when AAS_HTTP_TIMEOUT is not set."""
        client = build_async_client(TEST_BASE_URL)
        assert client.timeout.read == float(DEFAULT_HTTP_TIMEOUT)


class TestBearerTokenAuth:
    """Tests for BearerTokenAuth.auth_flow."""

    def _run_auth_flow(self, auth: BearerTokenAuth) -> httpx.Request:
        """Run auth_flow on a dummy request and return the modified request."""
        request = httpx.Request("GET", TEST_BASE_URL)
        flow = auth.auth_flow(request)
        next(flow)  # advance generator to the yield
        try:
            flow.send(MagicMock(spec=httpx.Response))  # send mock response
        except StopIteration:
            pass
        return request

    @patch("aas_mcp_server.http_client.get_access_token")
    def test_injects_bearer_token_when_token_present(self, mock_get_token):
        """Authorization: Bearer <token> is added when get_access_token() returns a token."""
        mock_token = MagicMock()
        mock_token.token = TEST_TOKEN
        mock_get_token.return_value = mock_token

        request = self._run_auth_flow(BearerTokenAuth())

        assert HEADER_AUTHORIZATION in request.headers
        assert request.headers[HEADER_AUTHORIZATION] == AUTH_BEARER_FORMAT.format(
            token=TEST_TOKEN
        )

    @patch("aas_mcp_server.http_client.get_access_token")
    def test_no_authorization_header_when_no_token(self, mock_get_token):
        """No Authorization header when get_access_token() returns None (stdio / no auth)."""
        mock_get_token.return_value = None

        request = self._run_auth_flow(BearerTokenAuth())

        assert HEADER_AUTHORIZATION not in request.headers

    @patch("aas_mcp_server.http_client.get_access_token")
    def test_token_value_used_verbatim(self, mock_get_token):
        """The exact token string from AccessToken.token is used in the header."""
        mock_token = MagicMock()
        mock_token.token = "eyJhbGciOiJSUzI1NiJ9.payload.signature"
        mock_get_token.return_value = mock_token

        request = self._run_auth_flow(BearerTokenAuth())

        assert "eyJhbGciOiJSUzI1NiJ9.payload.signature" in request.headers[HEADER_AUTHORIZATION]


class TestConstants:
    """Tests for module-level constants."""

    def test_default_timeout_value(self):
        assert DEFAULT_HTTP_TIMEOUT == 30

    def test_content_type_json(self):
        assert CONTENT_TYPE_JSON == "application/json"

    def test_auth_bearer_format(self):
        assert "{token}" in AUTH_BEARER_FORMAT
        assert AUTH_BEARER_FORMAT.startswith("Bearer ")
