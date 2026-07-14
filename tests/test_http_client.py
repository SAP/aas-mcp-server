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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import httpx

from aas_mcp_server.http_client import (
    BearerTokenAuth,
    build_async_client,
    validate_backend_url,
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

    def test_build_async_client_accepts_provider(self):
        """build_async_client uses the supplied provider in BearerTokenAuth."""
        from aas_mcp_server.backend_auth import NoneStrategy
        provider = NoneStrategy()
        client = build_async_client(TEST_BASE_URL, backend_token_provider=provider)
        assert isinstance(client.auth, BearerTokenAuth)
        assert client.auth._provider is provider


class TestBearerTokenAuth:
    """Tests for BearerTokenAuth.async_auth_flow."""

    async def _run_auth_flow(self, auth: BearerTokenAuth) -> httpx.Request:
        """Run async_auth_flow on a dummy request and return the modified request."""
        request = httpx.Request("GET", TEST_BASE_URL)
        flow = auth.async_auth_flow(request)
        await flow.__anext__()  # advance to yield
        try:
            await flow.athrow(StopAsyncIteration)
        except StopAsyncIteration:
            pass
        except Exception:
            pass
        return request

    @pytest.mark.asyncio
    async def test_injects_bearer_token_when_provider_returns_token(self):
        """Authorization: Bearer <token> is added when provider returns a token."""
        mock_provider = MagicMock()
        mock_provider.get_token = AsyncMock(return_value=TEST_TOKEN)

        request = await self._run_auth_flow(BearerTokenAuth(provider=mock_provider))

        assert HEADER_AUTHORIZATION in request.headers
        assert request.headers[HEADER_AUTHORIZATION] == AUTH_BEARER_FORMAT.format(token=TEST_TOKEN)

    @pytest.mark.asyncio
    async def test_no_authorization_header_when_provider_returns_none(self):
        """No Authorization header when provider returns None."""
        mock_provider = MagicMock()
        mock_provider.get_token = AsyncMock(return_value=None)

        request = await self._run_auth_flow(BearerTokenAuth(provider=mock_provider))

        assert HEADER_AUTHORIZATION not in request.headers

    @pytest.mark.asyncio
    async def test_token_value_used_verbatim(self):
        """The exact token string from the provider is used in the header."""
        token = "eyJhbGciOiJSUzI1NiJ9.payload.signature"
        mock_provider = MagicMock()
        mock_provider.get_token = AsyncMock(return_value=token)

        request = await self._run_auth_flow(BearerTokenAuth(provider=mock_provider))

        assert token in request.headers[HEADER_AUTHORIZATION]

    def test_uses_forward_strategy_by_default(self):
        """BearerTokenAuth defaults to ForwardStrategy when no provider supplied."""
        from aas_mcp_server.backend_auth import ForwardStrategy
        auth = BearerTokenAuth()
        assert isinstance(auth._provider, ForwardStrategy)

    @pytest.mark.asyncio
    async def test_no_token_content_in_debug_logs(self):
        """Token string must not appear in debug logs — even partial disclosure is a security risk."""
        import logging

        # Use a token where even the first 4 chars are unique enough to assert on
        token = "TOPSECRET-token-xyz"
        mock_provider = MagicMock()
        mock_provider.get_token = AsyncMock(return_value=token)

        # Install a handler directly on the module logger to capture records
        import aas_mcp_server.http_client as _mod
        captured = []

        class _Capture(logging.Handler):
            def emit(self, record):
                captured.append(self.format(record))

        handler = _Capture(level=logging.DEBUG)
        _mod.logger.addHandler(handler)
        old_level = _mod.logger.level
        _mod.logger.setLevel(logging.DEBUG)
        try:
            await self._run_auth_flow(BearerTokenAuth(provider=mock_provider))
        finally:
            _mod.logger.removeHandler(handler)
            _mod.logger.setLevel(old_level)

        all_output = " ".join(captured)
        # The token itself must not appear
        assert token not in all_output, f"Full token found in log output: {all_output!r}"
        # Nor any prefix of it (current code logs token[:6] = "TOPSEC")
        assert "TOPSEC" not in all_output, f"Token prefix found in log output: {all_output!r}"


class TestConstants:
    """Tests for module-level constants."""

    def test_default_timeout_value(self):
        assert DEFAULT_HTTP_TIMEOUT == 30

    def test_content_type_json(self):
        assert CONTENT_TYPE_JSON == "application/json"

    def test_auth_bearer_format(self):
        assert "{token}" in AUTH_BEARER_FORMAT
        assert AUTH_BEARER_FORMAT.startswith("Bearer ")


class TestValidateBackendUrl:
    """Tests for validate_backend_url — SSRF prevention.

    Scope: only scheme validation and literal cloud metadata IP blocking.
    RFC 1918 private addresses and Docker service hostnames are intentionally
    allowed — they are the most common AAS backend addresses in containerised
    deployments and pose no SSRF risk as operator-controlled configuration.
    """

    def test_valid_http_url_accepted(self):
        validate_backend_url("http://aas-backend:8081")

    def test_valid_https_url_accepted(self):
        validate_backend_url("https://aas.example.com/api")

    def test_localhost_accepted(self):
        validate_backend_url("http://localhost:8081")
        validate_backend_url("http://127.0.0.1:8081")

    def test_docker_service_hostname_accepted(self):
        """Docker service names (aas-env-rbac, aas-env, etc.) must be allowed.

        These resolve to RFC 1918 addresses by Docker's internal DNS — that is
        expected and intentional, not an SSRF risk.
        """
        validate_backend_url("http://aas-env-rbac:8081")
        validate_backend_url("http://aas-env:8081")

    def test_rfc1918_private_ip_accepted(self):
        """RFC 1918 addresses are legitimate Docker/on-premises backend IPs."""
        validate_backend_url("http://10.0.0.5:8081")
        validate_backend_url("http://172.22.0.7:8081")
        validate_backend_url("http://192.168.1.100:8081")

    def test_file_scheme_rejected(self):
        import pytest

        with pytest.raises(ValueError, match="scheme"):
            validate_backend_url("file:///etc/passwd")

    def test_ftp_scheme_rejected(self):
        import pytest

        with pytest.raises(ValueError, match="scheme"):
            validate_backend_url("ftp://internal-server/data")

    def test_cloud_metadata_ip_rejected(self):
        """169.254.169.254 (cloud metadata) must be blocked — never a valid backend."""
        import pytest

        with pytest.raises(ValueError, match="cloud metadata"):
            validate_backend_url("http://169.254.169.254/latest/meta-data/")

    def test_ipv4_mapped_ipv6_cloud_metadata_rejected(self):
        """IPv4-mapped IPv6 form of 169.254.169.254 must also be blocked."""
        import pytest

        with pytest.raises(ValueError, match="cloud metadata"):
            validate_backend_url("http://[::ffff:169.254.169.254]/")

    def test_no_redirects_on_client(self):
        """Client must not follow redirects to prevent open-redirect SSRF."""
        client = build_async_client("http://localhost:8081")
        assert client.follow_redirects is False


class TestAasHttpTimeoutValidation:
    """Tests for AAS_HTTP_TIMEOUT env var validation in build_async_client."""

    @patch.dict(os.environ, {"AAS_HTTP_TIMEOUT": "not-a-number"})
    def test_non_numeric_timeout_raises(self):
        """Non-numeric AAS_HTTP_TIMEOUT raises ValueError with env var name."""
        import pytest

        with pytest.raises(ValueError, match="AAS_HTTP_TIMEOUT"):
            build_async_client(TEST_BASE_URL)

    @patch.dict(os.environ, {"AAS_HTTP_TIMEOUT": "0"})
    def test_zero_timeout_raises(self):
        """AAS_HTTP_TIMEOUT=0 raises ValueError — must be > 0."""
        import pytest

        with pytest.raises(ValueError, match="AAS_HTTP_TIMEOUT"):
            build_async_client(TEST_BASE_URL)

    @patch.dict(os.environ, {"AAS_HTTP_TIMEOUT": "-5"})
    def test_negative_timeout_raises(self):
        """Negative AAS_HTTP_TIMEOUT raises ValueError."""
        import pytest

        with pytest.raises(ValueError, match="AAS_HTTP_TIMEOUT"):
            build_async_client(TEST_BASE_URL)

    @patch.dict(os.environ, {"AAS_HTTP_TIMEOUT": "0.1"})
    def test_small_positive_timeout_accepted(self):
        """Small positive float is a valid timeout."""
        client = build_async_client(TEST_BASE_URL)
        assert client.timeout.read == 0.1

    @patch.dict(os.environ, {"AAS_HTTP_TIMEOUT": "nan"})
    def test_nan_timeout_raises(self):
        """AAS_HTTP_TIMEOUT=nan raises ValueError — nan is not finite."""
        import pytest

        with pytest.raises(ValueError, match="AAS_HTTP_TIMEOUT"):
            build_async_client(TEST_BASE_URL)

    @patch.dict(os.environ, {"AAS_HTTP_TIMEOUT": "inf"})
    def test_inf_timeout_raises(self):
        """AAS_HTTP_TIMEOUT=inf raises ValueError — inf would create unbounded timeout."""
        import pytest

        with pytest.raises(ValueError, match="AAS_HTTP_TIMEOUT"):
            build_async_client(TEST_BASE_URL)

    @patch.dict(os.environ, {"AAS_HTTP_TIMEOUT": "-inf"})
    def test_negative_inf_timeout_raises(self):
        """AAS_HTTP_TIMEOUT=-inf raises ValueError."""
        import pytest

        with pytest.raises(ValueError, match="AAS_HTTP_TIMEOUT"):
            build_async_client(TEST_BASE_URL)
