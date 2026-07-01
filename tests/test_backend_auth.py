# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for backend_auth module — pluggable backend token strategies."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aas_mcp_server.backend_auth import (
    ForwardStrategy,
    NoneStrategy,
    TokenExchangeStrategy,
    build_backend_token_provider,
)
from aas_mcp_server.constants import (
    BACKEND_STRATEGY_FORWARD,
    BACKEND_STRATEGY_NONE,
    BACKEND_STRATEGY_TOKEN_EXCHANGE,
    ENV_BACKEND_AUTH_AUDIENCE,
    ENV_BACKEND_AUTH_CLIENT_ID,
    ENV_BACKEND_AUTH_CLIENT_SECRET,
    ENV_BACKEND_AUTH_SCOPE,
    ENV_BACKEND_AUTH_STRATEGY,
    ENV_BACKEND_AUTH_TOKEN_ENDPOINT,
    ENV_OAUTH_CLIENT_ID,
    ENV_OAUTH_CLIENT_SECRET,
    ENV_OAUTH_ISSUER_URL,
)


# ---------------------------------------------------------------------------
# ForwardStrategy
# ---------------------------------------------------------------------------

class TestForwardStrategy:
    @pytest.mark.asyncio
    async def test_returns_upstream_token(self):
        """ForwardStrategy returns the token from get_access_token()."""
        mock_token = MagicMock()
        mock_token.token = "upstream-token-abc"
        with patch("aas_mcp_server.backend_auth.get_access_token", return_value=mock_token):
            strategy = ForwardStrategy()
            result = await strategy.get_token()
        assert result == "upstream-token-abc"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_upstream_token(self):
        """ForwardStrategy returns None when get_access_token() returns None."""
        with patch("aas_mcp_server.backend_auth.get_access_token", return_value=None):
            strategy = ForwardStrategy()
            result = await strategy.get_token()
        assert result is None


# ---------------------------------------------------------------------------
# NoneStrategy
# ---------------------------------------------------------------------------

class TestNoneStrategy:
    @pytest.mark.asyncio
    async def test_always_returns_none(self):
        """NoneStrategy always returns None regardless of context."""
        strategy = NoneStrategy()
        result = await strategy.get_token()
        assert result is None


# ---------------------------------------------------------------------------
# TokenExchangeStrategy
# ---------------------------------------------------------------------------

class TestTokenExchangeStrategy:
    def _make_mock_client(self, json_response: dict, status_code: int = 200) -> AsyncMock:
        """Build a mock httpx.AsyncClient with a preset POST response."""
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = json_response

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        return mock_client, mock_response

    @pytest.mark.asyncio
    async def test_exchanges_upstream_token_for_backend_token(self):
        """TokenExchangeStrategy POSTs to token endpoint and returns access_token."""
        mock_upstream = MagicMock()
        mock_upstream.token = "user-upstream-token"

        mock_client, _ = self._make_mock_client({"access_token": "backend-token-xyz", "token_type": "Bearer"})

        with patch("aas_mcp_server.backend_auth.get_access_token", return_value=mock_upstream), \
             patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = TokenExchangeStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="mcp-client-id",
                client_secret="mcp-secret",
                audience="backend-client-id",
                scope=None,
            )
            result = await strategy.get_token()

        assert result == "backend-token-xyz"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_upstream_token(self):
        """TokenExchangeStrategy returns None when there is no upstream token to exchange."""
        with patch("aas_mcp_server.backend_auth.get_access_token", return_value=None):
            strategy = TokenExchangeStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="mcp-client-id",
                client_secret="mcp-secret",
                audience="backend-client-id",
                scope=None,
            )
            result = await strategy.get_token()
        assert result is None

    @pytest.mark.asyncio
    async def test_includes_scope_when_provided(self):
        """TokenExchangeStrategy includes scope in the token exchange request."""
        mock_upstream = MagicMock()
        mock_upstream.token = "user-token"

        mock_client, _ = self._make_mock_client({"access_token": "scoped-backend-token", "token_type": "Bearer"})

        with patch("aas_mcp_server.backend_auth.get_access_token", return_value=mock_upstream), \
             patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = TokenExchangeStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="mcp-client-id",
                client_secret="mcp-secret",
                audience="backend-client-id",
                scope="read write",
            )
            await strategy.get_token()

        call_kwargs = mock_client.post.call_args
        data = call_kwargs[1]["data"] if "data" in call_kwargs[1] else call_kwargs[0][1]
        assert "scope" in data
        assert data["scope"] == "read write"

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        """TokenExchangeStrategy raises RuntimeError when token endpoint returns an error."""
        import httpx as _httpx

        mock_upstream = MagicMock()
        mock_upstream.token = "user-token"

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.raise_for_status = MagicMock(
            side_effect=_httpx.HTTPStatusError("400", request=MagicMock(), response=mock_response)
        )
        mock_response.json.return_value = {"error": "invalid_grant"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("aas_mcp_server.backend_auth.get_access_token", return_value=mock_upstream), \
             patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = TokenExchangeStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="mcp-client-id",
                client_secret="mcp-secret",
                audience="backend-client-id",
                scope=None,
            )
            with pytest.raises(RuntimeError, match="token exchange"):
                await strategy.get_token()

    @pytest.mark.asyncio
    async def test_raises_on_missing_access_token_in_response(self):
        """TokenExchangeStrategy raises RuntimeError when response has no access_token field."""
        mock_upstream = MagicMock()
        mock_upstream.token = "user-token"

        mock_client, _ = self._make_mock_client({"token_type": "Bearer"})  # missing access_token

        with patch("aas_mcp_server.backend_auth.get_access_token", return_value=mock_upstream), \
             patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = TokenExchangeStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="mcp-client-id",
                client_secret="mcp-secret",
                audience="backend-client-id",
                scope=None,
            )
            with pytest.raises(RuntimeError, match="access_token"):
                await strategy.get_token()

    @pytest.mark.asyncio
    async def test_raises_on_non_json_response(self):
        """TokenExchangeStrategy raises RuntimeError when response is not valid JSON."""
        import httpx as _httpx

        mock_upstream = MagicMock()
        mock_upstream.token = "user-token"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {"content-type": "text/html"}
        mock_response.json.side_effect = _httpx.DecodingError("not json", request=MagicMock())

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("aas_mcp_server.backend_auth.get_access_token", return_value=mock_upstream), \
             patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = TokenExchangeStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="mcp-client-id",
                client_secret="mcp-secret",
                audience="backend-client-id",
                scope=None,
            )
            with pytest.raises(RuntimeError, match="[Jj][Ss][Oo][Nn]|[Pp]arse|[Rr]esponse"):
                await strategy.get_token()

    @pytest.mark.asyncio
    async def test_reuses_http_client_across_calls(self):
        """TokenExchangeStrategy reuses a single httpx.AsyncClient across multiple get_token calls."""
        mock_upstream = MagicMock()
        mock_upstream.token = "user-token"

        mock_client, _ = self._make_mock_client({"access_token": "backend-token", "token_type": "Bearer"})

        with patch("aas_mcp_server.backend_auth.get_access_token", return_value=mock_upstream), \
             patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client) as mock_client_cls:
            strategy = TokenExchangeStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="mcp-client-id",
                client_secret="mcp-secret",
                audience="backend-client-id",
                scope=None,
            )
            await strategy.get_token()
            await strategy.get_token()

        # AsyncClient() constructor should be called at most once (at init), not once per request
        assert mock_client_cls.call_count <= 1, (
            f"httpx.AsyncClient() was instantiated {mock_client_cls.call_count} times; "
            "expected at most 1 (client should be reused, not created per request)"
        )


# ---------------------------------------------------------------------------
# build_backend_token_provider factory
# ---------------------------------------------------------------------------

class TestBuildBackendTokenProvider:
    @patch.dict(os.environ, {}, clear=True)
    def test_returns_forward_strategy_when_no_config(self):
        """Returns ForwardStrategy when no BACKEND_AUTH_* vars are set."""
        provider = build_backend_token_provider()
        assert isinstance(provider, ForwardStrategy)

    @patch.dict(os.environ, {ENV_BACKEND_AUTH_STRATEGY: BACKEND_STRATEGY_NONE}, clear=True)
    def test_explicit_none_strategy(self):
        """BACKEND_AUTH_STRATEGY=none returns NoneStrategy."""
        provider = build_backend_token_provider()
        assert isinstance(provider, NoneStrategy)

    @patch.dict(os.environ, {ENV_BACKEND_AUTH_STRATEGY: BACKEND_STRATEGY_FORWARD}, clear=True)
    def test_explicit_forward_strategy(self):
        """BACKEND_AUTH_STRATEGY=forward returns ForwardStrategy."""
        provider = build_backend_token_provider()
        assert isinstance(provider, ForwardStrategy)

    @patch.dict(os.environ, {
        ENV_BACKEND_AUTH_AUDIENCE: "backend-client-id",
        ENV_BACKEND_AUTH_TOKEN_ENDPOINT: "https://idp.example.com/oauth/token",
        ENV_OAUTH_CLIENT_ID: "mcp-client-id",
        ENV_OAUTH_CLIENT_SECRET: "mcp-secret",
    }, clear=True)
    def test_auto_selects_token_exchange_when_audience_set(self):
        """Auto-selects TokenExchangeStrategy when BACKEND_AUTH_AUDIENCE is set."""
        provider = build_backend_token_provider()
        assert isinstance(provider, TokenExchangeStrategy)

    @patch.dict(os.environ, {
        ENV_BACKEND_AUTH_STRATEGY: BACKEND_STRATEGY_TOKEN_EXCHANGE,
        ENV_BACKEND_AUTH_TOKEN_ENDPOINT: "https://idp.example.com/oauth/token",
        ENV_OAUTH_CLIENT_ID: "mcp-client-id",
        ENV_OAUTH_CLIENT_SECRET: "mcp-secret",
    }, clear=True)
    def test_token_exchange_without_audience_raises(self):
        """token_exchange strategy without BACKEND_AUTH_AUDIENCE raises ValueError."""
        with pytest.raises(ValueError, match="BACKEND_AUTH_AUDIENCE"):
            build_backend_token_provider()

    @patch.dict(os.environ, {
        ENV_BACKEND_AUTH_STRATEGY: "invalid_strategy",
    }, clear=True)
    def test_invalid_strategy_raises(self):
        """Unknown strategy name raises ValueError."""
        with pytest.raises(ValueError, match="BACKEND_AUTH_STRATEGY"):
            build_backend_token_provider()

    @patch.dict(os.environ, {
        ENV_BACKEND_AUTH_AUDIENCE: "backend-client-id",
        ENV_OAUTH_CLIENT_ID: "mcp-client-id",
        ENV_OAUTH_CLIENT_SECRET: "mcp-secret",
        ENV_OAUTH_ISSUER_URL: "https://idp.example.com",
    }, clear=True)
    def test_token_endpoint_discovered_from_issuer_when_not_explicit(self):
        """When BACKEND_AUTH_TOKEN_ENDPOINT not set, token endpoint is derived from OAUTH_ISSUER_URL."""
        provider = build_backend_token_provider()
        assert isinstance(provider, TokenExchangeStrategy)
        assert "idp.example.com" in provider.token_endpoint

    @patch.dict(os.environ, {
        ENV_BACKEND_AUTH_AUDIENCE: "backend-client-id",
        ENV_BACKEND_AUTH_CLIENT_ID: "override-client-id",
        ENV_BACKEND_AUTH_CLIENT_SECRET: "override-secret",
        ENV_BACKEND_AUTH_TOKEN_ENDPOINT: "https://idp.example.com/oauth/token",
        ENV_OAUTH_CLIENT_ID: "mcp-client-id",
        ENV_OAUTH_CLIENT_SECRET: "mcp-secret",
    }, clear=True)
    def test_backend_client_id_overrides_oauth_client_id(self):
        """BACKEND_AUTH_CLIENT_ID overrides OAUTH_CLIENT_ID for token exchange."""
        provider = build_backend_token_provider()
        assert isinstance(provider, TokenExchangeStrategy)
        assert provider.client_id == "override-client-id"
        assert provider.client_secret == "override-secret"


# ---------------------------------------------------------------------------
# TokenExchangeStrategy.aclose()
# ---------------------------------------------------------------------------

class TestTokenExchangeStrategyClose:
    @pytest.mark.asyncio
    async def test_aclose_closes_http_client(self):
        """aclose() must close the underlying httpx.AsyncClient."""
        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client

            strategy = TokenExchangeStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                audience="aud",
                scope=None,
            )
            await strategy.aclose()

        mock_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_strategy_usable_as_async_context_manager(self):
        """TokenExchangeStrategy can be used as an async context manager; __aexit__ calls aclose()."""
        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client

            async with TokenExchangeStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                audience="aud",
                scope=None,
            ):
                pass

        mock_client.aclose.assert_awaited_once()
