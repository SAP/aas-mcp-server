# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""Tests for backend_auth module — pluggable backend token strategies."""

import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aas_mcp_server.backend_auth import (
    ClientCredentialsStrategy,
    ForwardStrategy,
    NoneStrategy,
    TokenExchangeStrategy,
    _discover_token_endpoint,
    _sanitize_endpoint_for_logging,
    build_backend_token_provider,
)
from aas_mcp_server.constants import (
    BACKEND_STRATEGY_CLIENT_CREDENTIALS,
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
    def _make_mock_client(self, json_response: dict, status_code: int = 200) -> tuple[AsyncMock, MagicMock]:
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

    # ------------------------------------------------------------------
    # Per-subject caching (issue #40)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_same_upstream_token_reuses_cached_exchange(self):
        """Two get_token() calls with the same upstream token → one POST to the IdP."""
        mock_upstream = MagicMock()
        mock_upstream.token = "same-user-token"

        mock_client, _ = self._make_mock_client(
            {"access_token": "backend-token", "token_type": "Bearer", "expires_in": 3600}
        )

        with patch("aas_mcp_server.backend_auth.get_access_token", return_value=mock_upstream), \
             patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = TokenExchangeStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="mcp-client-id",
                client_secret="mcp-secret",
                audience="backend-client-id",
                scope=None,
            )
            first = await strategy.get_token()
            second = await strategy.get_token()

        assert first == second == "backend-token"
        assert mock_client.post.await_count == 1

    @pytest.mark.asyncio
    async def test_different_upstream_tokens_get_independent_exchanges(self):
        """Two get_token() calls with different upstream tokens → two POSTs, each caller
        receives only its own exchanged token."""
        # Make the exchange response depend on the subject_token in the POST body.
        def build_response(subject_token: str):
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            resp.headers = {"content-type": "application/json"}
            resp.json.return_value = {
                "access_token": f"backend-for-{subject_token}",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
            return resp

        async def post(*args, **kwargs):
            subj = kwargs["data"]["subject_token"]
            return build_response(subj)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=post)

        upstream_a = MagicMock()
        upstream_a.token = "user-A-token"
        upstream_b = MagicMock()
        upstream_b.token = "user-B-token"

        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = TokenExchangeStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="mcp-client-id",
                client_secret="mcp-secret",
                audience="backend-client-id",
                scope=None,
            )

            with patch("aas_mcp_server.backend_auth.get_access_token", return_value=upstream_a):
                a_token = await strategy.get_token()
            with patch("aas_mcp_server.backend_auth.get_access_token", return_value=upstream_b):
                b_token = await strategy.get_token()
            # Now user A comes back — should hit the cache, not the IdP.
            with patch("aas_mcp_server.backend_auth.get_access_token", return_value=upstream_a):
                a_token_again = await strategy.get_token()

        # Per-subject isolation: A never gets B's token, B never gets A's.
        assert a_token == "backend-for-user-A-token"
        assert b_token == "backend-for-user-B-token"
        assert a_token_again == a_token
        assert mock_client.post.await_count == 2  # one per distinct upstream token

    @pytest.mark.asyncio
    async def test_upstream_b_never_receives_a_cached_exchanged_token(self):
        """Security-critical: even after A's exchange is cached, B's call must fetch
        a fresh token — never reuse A's cache entry under any circumstance."""
        upstream_a = MagicMock()
        upstream_a.token = "token-A"
        upstream_b = MagicMock()
        upstream_b.token = "token-B"

        responses = iter([
            {"access_token": "A-backend-token", "expires_in": 3600},
            {"access_token": "B-backend-token", "expires_in": 3600},
        ])

        async def post(*args, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.headers = {"content-type": "application/json"}
            resp.json.return_value = next(responses)
            return resp

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=post)

        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = TokenExchangeStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="mcp-client-id",
                client_secret="mcp-secret",
                audience="backend-client-id",
                scope=None,
            )
            with patch("aas_mcp_server.backend_auth.get_access_token", return_value=upstream_a):
                a_token = await strategy.get_token()
            with patch("aas_mcp_server.backend_auth.get_access_token", return_value=upstream_b):
                b_token = await strategy.get_token()

        assert a_token == "A-backend-token"
        assert b_token == "B-backend-token"
        assert a_token != b_token
        assert mock_client.post.await_count == 2

    @pytest.mark.asyncio
    async def test_expired_exchanged_token_triggers_reexchange(self):
        """Once a cached exchange is past the expiry buffer, next get_token() re-exchanges."""
        mock_upstream = MagicMock()
        mock_upstream.token = "user-token"

        responses = iter([
            {"access_token": "backend-token-1", "expires_in": 3600},
            {"access_token": "backend-token-2", "expires_in": 3600},
        ])

        async def post(*args, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.headers = {"content-type": "application/json"}
            resp.json.return_value = next(responses)
            return resp

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=post)

        with patch("aas_mcp_server.backend_auth.get_access_token", return_value=mock_upstream), \
             patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = TokenExchangeStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="mcp-client-id",
                client_secret="mcp-secret",
                audience="backend-client-id",
                scope=None,
            )
            first = await strategy.get_token()

            # Reach into the cache and force the sole entry to look expired.
            for entry in strategy._cache._entries.values():  # type: ignore[attr-defined]
                entry.expires_at = 0.0

            second = await strategy.get_token()

        assert first == "backend-token-1"
        assert second == "backend-token-2"
        assert mock_client.post.await_count == 2

    @pytest.mark.asyncio
    async def test_concurrent_same_user_requests_coalesce(self):
        """N parallel get_token() calls for the same upstream token → one exchange only."""
        import asyncio

        mock_upstream = MagicMock()
        mock_upstream.token = "user-token"

        # Make the mocked POST slow so concurrent callers actually pile up on the lock.
        async def slow_post(*args, **kwargs):
            await asyncio.sleep(0.02)
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.headers = {"content-type": "application/json"}
            resp.json.return_value = {"access_token": "coalesced-backend-token", "expires_in": 3600}
            return resp

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=slow_post)

        with patch("aas_mcp_server.backend_auth.get_access_token", return_value=mock_upstream), \
             patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = TokenExchangeStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="mcp-client-id",
                client_secret="mcp-secret",
                audience="backend-client-id",
                scope=None,
            )
            results = await asyncio.gather(*(strategy.get_token() for _ in range(5)))

        assert all(r == "coalesced-backend-token" for r in results)
        assert mock_client.post.await_count == 1


# ---------------------------------------------------------------------------
# ClientCredentialsStrategy
# ---------------------------------------------------------------------------

class TestClientCredentialsStrategy:
    def _make_mock_client(self, json_response: dict, status_code: int = 200):
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
    async def test_fetches_token_from_endpoint(self):
        """POSTs client_credentials grant to the token endpoint and returns access_token."""
        mock_client, _ = self._make_mock_client(
            {"access_token": "svc-token-xyz", "token_type": "Bearer", "expires_in": 3600}
        )

        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="svc-client-id",
                client_secret="svc-secret",
                scope=None,
                audience=None,
            )
            result = await strategy.get_token()

        assert result == "svc-token-xyz"
        call_kwargs = mock_client.post.call_args
        data = call_kwargs.kwargs["data"]
        assert data["grant_type"] == "client_credentials"

    @pytest.mark.asyncio
    async def test_works_without_upstream_user_context(self):
        """ClientCredentialsStrategy does not depend on get_access_token() — no user context needed."""
        mock_client, _ = self._make_mock_client(
            {"access_token": "svc-token", "expires_in": 3600}
        )

        # Intentionally do NOT patch get_access_token — this strategy must not call it.
        with patch("aas_mcp_server.backend_auth.get_access_token") as spy_get_access_token, \
             patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                scope=None,
                audience=None,
            )
            result = await strategy.get_token()

        assert result == "svc-token"
        spy_get_access_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_includes_scope_when_provided(self):
        """`scope` is included in the token request body when set."""
        mock_client, _ = self._make_mock_client(
            {"access_token": "scoped-token", "expires_in": 3600}
        )
        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                scope="read write",
                audience=None,
            )
            await strategy.get_token()

        data = mock_client.post.call_args.kwargs["data"]
        assert data.get("scope") == "read write"

    @pytest.mark.asyncio
    async def test_omits_scope_when_absent(self):
        """`scope` is not present in the request body when not set."""
        mock_client, _ = self._make_mock_client(
            {"access_token": "token", "expires_in": 3600}
        )
        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                scope=None,
                audience=None,
            )
            await strategy.get_token()

        data = mock_client.post.call_args.kwargs["data"]
        assert "scope" not in data

    @pytest.mark.asyncio
    async def test_includes_audience_when_provided(self):
        """`audience` is included in the token request body when set (for Auth0/SAP IAS style IdPs)."""
        mock_client, _ = self._make_mock_client(
            {"access_token": "aud-token", "expires_in": 3600}
        )
        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                scope=None,
                audience="https://api.example.com",
            )
            await strategy.get_token()

        data = mock_client.post.call_args.kwargs["data"]
        assert data.get("audience") == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_omits_audience_when_absent(self):
        """`audience` is not present in the request body when not set."""
        mock_client, _ = self._make_mock_client(
            {"access_token": "token", "expires_in": 3600}
        )
        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                scope=None,
                audience=None,
            )
            await strategy.get_token()

        data = mock_client.post.call_args.kwargs["data"]
        assert "audience" not in data

    @pytest.mark.asyncio
    async def test_caches_token_across_calls(self):
        """Two sequential get_token() calls result in a single HTTP POST — token is cached."""
        mock_client, _ = self._make_mock_client(
            {"access_token": "cached-token", "expires_in": 3600}
        )
        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                scope=None,
                audience=None,
            )
            first = await strategy.get_token()
            second = await strategy.get_token()

        assert first == second == "cached-token"
        assert mock_client.post.await_count == 1

    @pytest.mark.asyncio
    async def test_refreshes_after_expiry(self):
        """After the cached token's expiry passes, the next call re-fetches."""
        mock_client, _ = self._make_mock_client(
            {"access_token": "token-1", "expires_in": 3600}
        )
        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                scope=None,
                audience=None,
            )
            await strategy.get_token()
            # Force the cached token to appear expired (past the buffer window).
            for entry in strategy._cache._entries.values():
                entry.expires_at = 0.0
            # Change what the mock will return on the next call so we can distinguish.
            mock_client.post.return_value.json.return_value = {
                "access_token": "token-2", "expires_in": 3600,
            }
            second = await strategy.get_token()

        assert second == "token-2"
        assert mock_client.post.await_count == 2

    @pytest.mark.asyncio
    async def test_concurrent_calls_fetch_once(self):
        """Concurrent get_token() calls during a fetch coalesce — only one HTTP POST is made."""
        import asyncio

        mock_client, _ = self._make_mock_client(
            {"access_token": "coalesced-token", "expires_in": 3600}
        )
        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                scope=None,
                audience=None,
            )
            results = await asyncio.gather(*(strategy.get_token() for _ in range(5)))

        assert all(r == "coalesced-token" for r in results)
        assert mock_client.post.await_count == 1

    @pytest.mark.asyncio
    async def test_defaults_expiry_when_response_omits_expires_in(self):
        """When the response has no `expires_in`, strategy still caches (using default lifetime)."""
        mock_client, _ = self._make_mock_client({"access_token": "no-expiry-token"})
        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                scope=None,
                audience=None,
            )
            first = await strategy.get_token()
            second = await strategy.get_token()

        assert first == second == "no-expiry-token"
        # Cache is populated with a non-zero expiry so the second call hits the cache.
        assert mock_client.post.await_count == 1
        # Fallback lifetime kicked in: the sole cache entry has a live expires_at.
        assert all(entry.expires_at > 0 for entry in strategy._cache._entries.values())
        assert len(strategy._cache._entries) == 1

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        """A 4xx/5xx from the IdP raises RuntimeError with an actionable message."""
        import httpx as _httpx

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status = MagicMock(
            side_effect=_httpx.HTTPStatusError("401", request=MagicMock(), response=mock_response)
        )
        mock_response.json.return_value = {"error": "invalid_client"}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                scope=None,
                audience=None,
            )
            with pytest.raises(RuntimeError, match="client_credentials"):
                await strategy.get_token()

    @pytest.mark.asyncio
    async def test_raises_on_missing_access_token_in_response(self):
        """A 200 response without access_token raises RuntimeError."""
        mock_client, _ = self._make_mock_client({"token_type": "Bearer"})
        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                scope=None,
                audience=None,
            )
            with pytest.raises(RuntimeError, match="access_token"):
                await strategy.get_token()

    @pytest.mark.asyncio
    async def test_raises_on_non_json_response(self):
        """A response with a non-JSON body raises RuntimeError."""
        import httpx as _httpx

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.headers = {"content-type": "text/html"}
        mock_response.json.side_effect = _httpx.DecodingError("not json", request=MagicMock())
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                scope=None,
                audience=None,
            )
            with pytest.raises(RuntimeError, match="non-JSON|JSON|response"):
                await strategy.get_token()

    @pytest.mark.asyncio
    async def test_raises_on_network_error(self):
        """A network / connection failure raises RuntimeError pointing at the endpoint."""
        import httpx as _httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=_httpx.RequestError("connection refused"))

        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                scope=None,
                audience=None,
            )
            with pytest.raises(RuntimeError, match="BACKEND_AUTH_TOKEN_ENDPOINT"):
                await strategy.get_token()

    @pytest.mark.asyncio
    async def test_reuses_http_client_across_calls(self):
        """A single httpx.AsyncClient is constructed at init and reused."""
        mock_client, _ = self._make_mock_client(
            {"access_token": "token", "expires_in": 3600}
        )
        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client) as mock_cls:
            strategy = ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                scope=None,
                audience=None,
            )
            await strategy.get_token()
            # Force refresh, hit the endpoint again.
            for entry in strategy._cache._entries.values():
                entry.expires_at = 0.0
            await strategy.get_token()

        assert mock_cls.call_count <= 1


# ---------------------------------------------------------------------------
# ClientCredentialsStrategy.aclose()
# ---------------------------------------------------------------------------

class TestClientCredentialsStrategyClose:
    @pytest.mark.asyncio
    async def test_aclose_closes_http_client(self):
        """aclose() closes the underlying httpx.AsyncClient."""
        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client

            strategy = ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                scope=None,
                audience=None,
            )
            await strategy.aclose()

        mock_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_strategy_usable_as_async_context_manager(self):
        """Async context manager exit calls aclose()."""
        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client

            async with ClientCredentialsStrategy(
                token_endpoint="https://idp.example.com/oauth/token",
                client_id="cid",
                client_secret="csec",
                scope=None,
                audience=None,
            ):
                pass

        mock_client.aclose.assert_awaited_once()


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

    @patch("aas_mcp_server.backend_auth.httpx.get")
    @patch.dict(os.environ, {
        ENV_BACKEND_AUTH_AUDIENCE: "backend-client-id",
        ENV_OAUTH_CLIENT_ID: "mcp-client-id",
        ENV_OAUTH_CLIENT_SECRET: "mcp-secret",
        ENV_OAUTH_ISSUER_URL: "https://idp.example.com",
    }, clear=True)
    def test_token_endpoint_discovered_from_issuer_when_not_explicit(self, mock_get):
        """When BACKEND_AUTH_TOKEN_ENDPOINT not set, token endpoint is discovered via OIDC metadata."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.raise_for_status = lambda: None
        mock_get.return_value.json.return_value = {
            "token_endpoint": "https://idp.example.com/oauth2/token"
        }
        provider = build_backend_token_provider()
        assert isinstance(provider, TokenExchangeStrategy)
        assert provider.token_endpoint == "https://idp.example.com/oauth2/token"
        mock_get.assert_called_once_with(
            "https://idp.example.com/.well-known/openid-configuration", timeout=5.0
        )

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

    @patch.dict(os.environ, {
        ENV_BACKEND_AUTH_STRATEGY: BACKEND_STRATEGY_CLIENT_CREDENTIALS,
        ENV_BACKEND_AUTH_TOKEN_ENDPOINT: "https://idp.example.com/oauth/token",
        ENV_BACKEND_AUTH_CLIENT_ID: "svc-cid",
        ENV_BACKEND_AUTH_CLIENT_SECRET: "svc-csec",
    }, clear=True)
    def test_client_credentials_strategy_selected_explicitly(self):
        """BACKEND_AUTH_STRATEGY=client_credentials with creds builds ClientCredentialsStrategy."""
        provider = build_backend_token_provider()
        assert isinstance(provider, ClientCredentialsStrategy)
        assert provider.token_endpoint == "https://idp.example.com/oauth/token"
        assert provider.client_id == "svc-cid"
        assert provider.client_secret == "svc-csec"
        assert provider.scope is None
        assert provider.audience is None

    @patch.dict(os.environ, {
        ENV_BACKEND_AUTH_STRATEGY: BACKEND_STRATEGY_CLIENT_CREDENTIALS,
        ENV_BACKEND_AUTH_TOKEN_ENDPOINT: "https://idp.example.com/oauth/token",
        ENV_BACKEND_AUTH_CLIENT_ID: "svc-cid",
        ENV_BACKEND_AUTH_CLIENT_SECRET: "svc-csec",
        ENV_BACKEND_AUTH_SCOPE: "api.read",
        ENV_BACKEND_AUTH_AUDIENCE: "https://api.example.com",
    }, clear=True)
    def test_client_credentials_forwards_scope_and_audience(self):
        """Optional scope and audience env vars flow through into the strategy."""
        provider = build_backend_token_provider()
        assert isinstance(provider, ClientCredentialsStrategy)
        assert provider.scope == "api.read"
        assert provider.audience == "https://api.example.com"

    @patch.dict(os.environ, {
        ENV_BACKEND_AUTH_STRATEGY: BACKEND_STRATEGY_CLIENT_CREDENTIALS,
        ENV_BACKEND_AUTH_TOKEN_ENDPOINT: "https://idp.example.com/oauth/token",
        ENV_BACKEND_AUTH_CLIENT_SECRET: "svc-csec",
    }, clear=True)
    def test_client_credentials_missing_client_id_raises(self):
        """Missing client_id (no BACKEND_AUTH_CLIENT_ID nor OAUTH_CLIENT_ID) raises ValueError."""
        with pytest.raises(ValueError, match="client ID"):
            build_backend_token_provider()

    @patch.dict(os.environ, {
        ENV_BACKEND_AUTH_STRATEGY: BACKEND_STRATEGY_CLIENT_CREDENTIALS,
        ENV_BACKEND_AUTH_TOKEN_ENDPOINT: "https://idp.example.com/oauth/token",
        ENV_BACKEND_AUTH_CLIENT_ID: "svc-cid",
    }, clear=True)
    def test_client_credentials_missing_client_secret_raises(self):
        """Missing client secret raises ValueError."""
        with pytest.raises(ValueError, match="client secret"):
            build_backend_token_provider()

    @patch.dict(os.environ, {
        ENV_BACKEND_AUTH_STRATEGY: BACKEND_STRATEGY_CLIENT_CREDENTIALS,
        ENV_BACKEND_AUTH_CLIENT_ID: "svc-cid",
        ENV_BACKEND_AUTH_CLIENT_SECRET: "svc-csec",
    }, clear=True)
    def test_client_credentials_no_endpoint_or_issuer_raises(self):
        """Missing both BACKEND_AUTH_TOKEN_ENDPOINT and OAUTH_ISSUER_URL raises ValueError."""
        with pytest.raises(ValueError, match="BACKEND_AUTH_TOKEN_ENDPOINT"):
            build_backend_token_provider()

    @patch("aas_mcp_server.backend_auth.httpx.get")
    @patch.dict(os.environ, {
        ENV_BACKEND_AUTH_STRATEGY: BACKEND_STRATEGY_CLIENT_CREDENTIALS,
        ENV_BACKEND_AUTH_CLIENT_ID: "svc-cid",
        ENV_BACKEND_AUTH_CLIENT_SECRET: "svc-csec",
        ENV_OAUTH_ISSUER_URL: "https://idp.example.com",
    }, clear=True)
    def test_client_credentials_uses_oidc_discovery_when_no_endpoint(self, mock_get):
        """When token endpoint isn't set, it's discovered via OIDC metadata (as for token_exchange)."""
        mock_get.return_value.raise_for_status = lambda: None
        mock_get.return_value.json.return_value = {
            "token_endpoint": "https://idp.example.com/oauth2/token"
        }
        provider = build_backend_token_provider()
        assert isinstance(provider, ClientCredentialsStrategy)
        assert provider.token_endpoint == "https://idp.example.com/oauth2/token"

    @patch.dict(os.environ, {
        ENV_BACKEND_AUTH_AUDIENCE: "backend-client-id",
        ENV_BACKEND_AUTH_TOKEN_ENDPOINT: "https://idp.example.com/oauth/token",
        ENV_OAUTH_CLIENT_ID: "mcp-client-id",
        ENV_OAUTH_CLIENT_SECRET: "mcp-secret",
    }, clear=True)
    def test_audience_alone_does_not_select_client_credentials(self):
        """Setting BACKEND_AUTH_AUDIENCE without explicit strategy still routes to token_exchange."""
        provider = build_backend_token_provider()
        assert isinstance(provider, TokenExchangeStrategy)
        assert not isinstance(provider, ClientCredentialsStrategy)


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


# ---------------------------------------------------------------------------
# _discover_token_endpoint
# ---------------------------------------------------------------------------

class TestDiscoverTokenEndpoint:
    @patch("aas_mcp_server.backend_auth.httpx.get")
    def test_success_returns_token_endpoint(self, mock_get):
        """Returns token_endpoint from the OIDC discovery document."""
        mock_get.return_value.raise_for_status = lambda: None
        mock_get.return_value.json.return_value = {
            "token_endpoint": "https://idp.example.com/oauth2/token",
            "issuer": "https://idp.example.com",
        }
        result = _discover_token_endpoint("https://idp.example.com")
        assert result == "https://idp.example.com/oauth2/token"
        mock_get.assert_called_once_with(
            "https://idp.example.com/.well-known/openid-configuration", timeout=5.0
        )

    @patch("aas_mcp_server.backend_auth.httpx.get")
    def test_strips_trailing_slash_from_issuer(self, mock_get):
        """Trailing slash on issuer URL is normalised before constructing discovery URL."""
        mock_get.return_value.raise_for_status = lambda: None
        mock_get.return_value.json.return_value = {"token_endpoint": "https://idp.example.com/token"}
        _discover_token_endpoint("https://idp.example.com/")
        mock_get.assert_called_once_with(
            "https://idp.example.com/.well-known/openid-configuration", timeout=5.0
        )

    @patch("aas_mcp_server.backend_auth.httpx.get")
    def test_strips_existing_openid_configuration_suffix(self, mock_get):
        """Issuer URL that already ends with /.well-known/openid-configuration is normalised."""
        mock_get.return_value.raise_for_status = lambda: None
        mock_get.return_value.json.return_value = {"token_endpoint": "https://idp.example.com/token"}
        _discover_token_endpoint("https://idp.example.com/.well-known/openid-configuration")
        mock_get.assert_called_once_with(
            "https://idp.example.com/.well-known/openid-configuration", timeout=5.0
        )

    @patch("aas_mcp_server.backend_auth.httpx.get")
    def test_non_standard_path_ending_openid_configuration_not_corrupted(self, mock_get):
        """Issuer URL ending in /openid-configuration (without /.well-known) is handled correctly.

        Expected: /openid-configuration is stripped and /.well-known/openid-configuration appended,
        producing the correct discovery URL without double-appending or truncating.
        """
        mock_get.return_value.raise_for_status = lambda: None
        mock_get.return_value.json.return_value = {"token_endpoint": "https://idp.example.com/token"}
        _discover_token_endpoint("https://idp.example.com/auth/openid-configuration")
        called_url = mock_get.call_args[0][0]
        assert called_url == "https://idp.example.com/auth/.well-known/openid-configuration"

    @patch("aas_mcp_server.backend_auth.httpx.get")
    def test_raises_on_http_status_error(self, mock_get):
        """Non-2xx HTTP response raises ValueError with actionable message."""
        import httpx as _httpx
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value.raise_for_status.side_effect = _httpx.HTTPStatusError(
            "404", request=MagicMock(), response=mock_response
        )
        with pytest.raises(ValueError, match="BACKEND_AUTH_TOKEN_ENDPOINT"):
            _discover_token_endpoint("https://idp.example.com")

    @patch("aas_mcp_server.backend_auth.httpx.get")
    def test_raises_on_request_error(self, mock_get):
        """Network / timeout error raises ValueError directing operator to explicit config."""
        import httpx as _httpx
        mock_get.side_effect = _httpx.RequestError("timeout")
        with pytest.raises(ValueError, match="BACKEND_AUTH_TOKEN_ENDPOINT"):
            _discover_token_endpoint("https://idp.example.com")

    @patch("aas_mcp_server.backend_auth.httpx.get")
    def test_raises_when_token_endpoint_missing_from_metadata(self, mock_get):
        """Discovery document without token_endpoint raises ValueError."""
        mock_get.return_value.raise_for_status = lambda: None
        mock_get.return_value.json.return_value = {"issuer": "https://idp.example.com"}
        with pytest.raises(ValueError, match="token_endpoint"):
            _discover_token_endpoint("https://idp.example.com")


# ---------------------------------------------------------------------------
# Endpoint sanitization for logs and error messages (#42)
# ---------------------------------------------------------------------------

class TestSanitizeEndpointForLogging:
    def test_plain_url_is_unchanged(self):
        assert (
            _sanitize_endpoint_for_logging("https://idp.example.com/oauth/token")
            == "https://idp.example.com/oauth/token"
        )

    def test_keeps_explicit_port(self):
        assert (
            _sanitize_endpoint_for_logging("https://idp.example.com:8443/oauth/token")
            == "https://idp.example.com:8443/oauth/token"
        )

    def test_rewraps_ipv6_host_in_brackets(self):
        """urlparse().hostname drops the brackets; without them the URL is malformed."""
        assert (
            _sanitize_endpoint_for_logging("https://[::1]:8080/oauth/token")
            == "https://[::1]:8080/oauth/token"
        )

    def test_rewraps_ipv6_host_without_port(self):
        assert (
            _sanitize_endpoint_for_logging("https://[2001:db8::1]/oauth/token")
            == "https://[2001:db8::1]/oauth/token"
        )

    def test_drops_query_and_fragment(self):
        assert (
            _sanitize_endpoint_for_logging("https://idp.example.com/oauth/token?client_secret=s3cr3t#frag")
            == "https://idp.example.com/oauth/token"
        )

    def test_drops_userinfo(self):
        assert (
            _sanitize_endpoint_for_logging("https://user:pass@idp.example.com/oauth/token")
            == "https://idp.example.com/oauth/token"
        )

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "idp.example.com/oauth/token",
            "https:///oauth/token",
            "https://idp.example.com:notaport/oauth/token",
        ],
    )
    def test_rejects_url_without_scheme_host_or_integer_port(self, bad):
        with pytest.raises(ValueError):
            _sanitize_endpoint_for_logging(bad)


class TestStrategiesDoNotLeakRawEndpoint:
    """The request goes to the full endpoint; logs and errors only ever see the sanitized one."""

    RAW_ENDPOINT = "https://idp.example.com/oauth/token?client_secret=s3cr3t"
    SAFE_ENDPOINT = "https://idp.example.com/oauth/token"

    def _token_exchange(self) -> TokenExchangeStrategy:
        return TokenExchangeStrategy(
            token_endpoint=self.RAW_ENDPOINT,
            client_id="mcp-client-id",
            client_secret="mcp-secret",
            audience="backend-client-id",
            scope=None,
        )

    def _client_credentials(self) -> ClientCredentialsStrategy:
        return ClientCredentialsStrategy(
            token_endpoint=self.RAW_ENDPOINT,
            client_id="cid",
            client_secret="csec",
            scope=None,
            audience=None,
        )

    @pytest.mark.asyncio
    async def test_token_exchange_http_error_message_is_sanitized(self):
        import httpx as _httpx

        mock_upstream = MagicMock()
        mock_upstream.token = "user-token"
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.raise_for_status = MagicMock(
            side_effect=_httpx.HTTPStatusError("400", request=MagicMock(), response=mock_response)
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("aas_mcp_server.backend_auth.get_access_token", return_value=mock_upstream), \
             patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = self._token_exchange()
            with pytest.raises(RuntimeError) as exc_info:
                await strategy.get_token()

        assert "s3cr3t" not in str(exc_info.value)
        assert self.SAFE_ENDPOINT in str(exc_info.value)
        # The request itself must still go to the endpoint exactly as configured.
        assert mock_client.post.await_args.args[0] == self.RAW_ENDPOINT

    @pytest.mark.asyncio
    async def test_token_exchange_debug_log_is_sanitized(self, caplog):
        mock_upstream = MagicMock()
        mock_upstream.token = "user-token"
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"access_token": "backend-token"}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        caplog.set_level(logging.DEBUG, logger="aas_mcp_server.backend_auth")
        with patch("aas_mcp_server.backend_auth.get_access_token", return_value=mock_upstream), \
             patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            assert await self._token_exchange().get_token() == "backend-token"

        assert "s3cr3t" not in caplog.text
        assert self.SAFE_ENDPOINT in caplog.text

    @pytest.mark.asyncio
    async def test_client_credentials_network_error_message_is_sanitized(self):
        import httpx as _httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=_httpx.RequestError("connection refused"))

        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            strategy = self._client_credentials()
            with pytest.raises(RuntimeError) as exc_info:
                await strategy.get_token()

        assert "s3cr3t" not in str(exc_info.value)
        assert f"BACKEND_AUTH_TOKEN_ENDPOINT ({self.SAFE_ENDPOINT})" in str(exc_info.value)
        assert mock_client.post.await_args.args[0] == self.RAW_ENDPOINT

    @pytest.mark.asyncio
    async def test_client_credentials_debug_log_is_sanitized(self, caplog):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"access_token": "svc-token", "expires_in": 3600}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        caplog.set_level(logging.DEBUG, logger="aas_mcp_server.backend_auth")
        with patch("aas_mcp_server.backend_auth.httpx.AsyncClient", return_value=mock_client):
            assert await self._client_credentials().get_token() == "svc-token"

        assert "s3cr3t" not in caplog.text
        assert self.SAFE_ENDPOINT in caplog.text

    def test_invalid_endpoint_is_rejected_at_construction(self):
        with pytest.raises(ValueError):
            ClientCredentialsStrategy(
                token_endpoint="not a url",
                client_id="cid",
                client_secret="csec",
                scope=None,
                audience=None,
            )


class TestFactoryLogsSanitizedEndpoint:
    RAW_IPV6_ENDPOINT = "https://[::1]:8080/oauth/token?client_secret=s3cr3t"

    @patch.dict(os.environ, {
        ENV_BACKEND_AUTH_STRATEGY: BACKEND_STRATEGY_CLIENT_CREDENTIALS,
        ENV_BACKEND_AUTH_TOKEN_ENDPOINT: RAW_IPV6_ENDPOINT,
        ENV_BACKEND_AUTH_CLIENT_ID: "svc-cid",
        ENV_BACKEND_AUTH_CLIENT_SECRET: "svc-csec",
    }, clear=True)
    def test_client_credentials_info_log_brackets_ipv6_and_drops_query(self, caplog):
        caplog.set_level(logging.INFO, logger="aas_mcp_server.backend_auth")
        provider = build_backend_token_provider()
        assert isinstance(provider, ClientCredentialsStrategy)
        assert provider.token_endpoint == self.RAW_IPV6_ENDPOINT
        assert "endpoint=https://[::1]:8080/oauth/token scope=" in caplog.text
        assert "s3cr3t" not in caplog.text

    @patch.dict(os.environ, {
        ENV_BACKEND_AUTH_AUDIENCE: "backend-client-id",
        ENV_BACKEND_AUTH_TOKEN_ENDPOINT: RAW_IPV6_ENDPOINT,
        ENV_BACKEND_AUTH_CLIENT_ID: "mcp-cid",
        ENV_BACKEND_AUTH_CLIENT_SECRET: "mcp-csec",
    }, clear=True)
    def test_token_exchange_info_log_brackets_ipv6_and_drops_query(self, caplog):
        caplog.set_level(logging.INFO, logger="aas_mcp_server.backend_auth")
        provider = build_backend_token_provider()
        assert isinstance(provider, TokenExchangeStrategy)
        assert provider.token_endpoint == self.RAW_IPV6_ENDPOINT
        assert "endpoint=https://[::1]:8080/oauth/token audience=" in caplog.text
        assert "s3cr3t" not in caplog.text


# ---------------------------------------------------------------------------
# _KeyedTokenCache — shared caching helper used by both token-issuing strategies
# ---------------------------------------------------------------------------

class TestKeyedTokenCache:
    """Unit tests for the private _KeyedTokenCache helper.

    The cache stores per-key backend tokens with monotonic-clock expiry, an
    expiry buffer window, per-key lock coalescing, and bounded LRU eviction.
    Both ClientCredentialsStrategy and TokenExchangeStrategy delegate their
    caching to instances of this class.
    """

    def _import_cache(self):
        """Import the class lazily so import failure surfaces as a test failure,
        not a collection error that hides all other tests in the file."""
        from aas_mcp_server.backend_auth import _KeyedTokenCache  # type: ignore[attr-defined]
        return _KeyedTokenCache

    @pytest.mark.asyncio
    async def test_hit_within_lifetime_does_not_refetch(self):
        """A second get_or_fetch under the same key within the token's lifetime
        returns the cached token and does not invoke fetch() again."""
        _KeyedTokenCache = self._import_cache()
        cache = _KeyedTokenCache()

        calls = 0

        async def fetch():
            nonlocal calls
            calls += 1
            return ("tok", 3600)

        first = await cache.get_or_fetch("k", fetch, label="test")
        second = await cache.get_or_fetch("k", fetch, label="test")

        assert first == second == "tok"
        assert calls == 1

    @pytest.mark.asyncio
    async def test_refetches_past_expiry_buffer(self):
        """Once the cached entry falls inside the expiry buffer window, the next
        call re-invokes fetch() and returns the new token."""
        _KeyedTokenCache = self._import_cache()
        cache = _KeyedTokenCache()

        results = iter([("tok-1", 3600), ("tok-2", 3600)])

        async def fetch():
            return next(results)

        assert await cache.get_or_fetch("k", fetch, label="test") == "tok-1"

        # Force the cached entry to appear expired.
        cache._entries["k"].expires_at = 0.0  # type: ignore[attr-defined]

        assert await cache.get_or_fetch("k", fetch, label="test") == "tok-2"

    @pytest.mark.asyncio
    async def test_expires_in_missing_uses_default_lifetime(self):
        """When fetch() returns expires_in <= 0, the cache falls back to
        DEFAULT_TOKEN_LIFETIME_SECONDS so the entry is still reusable."""
        from aas_mcp_server.backend_auth import DEFAULT_TOKEN_LIFETIME_SECONDS

        _KeyedTokenCache = self._import_cache()
        cache = _KeyedTokenCache()

        calls = 0

        async def fetch():
            nonlocal calls
            calls += 1
            return ("tok", 0)  # sentinel: unknown/invalid expires_in

        await cache.get_or_fetch("k", fetch, label="test")
        # Second call — must be a cache hit if the fallback lifetime was applied.
        await cache.get_or_fetch("k", fetch, label="test")

        assert calls == 1
        entry = cache._entries["k"]  # type: ignore[attr-defined]
        # The stored expiry is now+fallback (much larger than 0).
        import time as _time
        assert entry.expires_at > _time.monotonic() + DEFAULT_TOKEN_LIFETIME_SECONDS - 60

    @pytest.mark.asyncio
    async def test_distinct_keys_are_isolated(self):
        """Two keys give two independent entries — never share a cached token."""
        _KeyedTokenCache = self._import_cache()
        cache = _KeyedTokenCache()

        fetches: list[str] = []

        async def make_fetch(name):
            async def fetch():
                fetches.append(name)
                return (f"tok-{name}", 3600)
            return fetch

        assert await cache.get_or_fetch("a", await make_fetch("A"), label="test") == "tok-A"
        assert await cache.get_or_fetch("b", await make_fetch("B"), label="test") == "tok-B"
        # Second call for A must return A's token, not B's.
        assert await cache.get_or_fetch("a", await make_fetch("A"), label="test") == "tok-A"

        assert fetches == ["A", "B"]  # A cached on second call, no refetch

    @pytest.mark.asyncio
    async def test_concurrent_same_key_coalesces_to_one_fetch(self):
        """N concurrent get_or_fetch calls for the same key produce exactly one fetch."""
        import asyncio

        _KeyedTokenCache = self._import_cache()
        cache = _KeyedTokenCache()

        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def fetch():
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()  # hold the fetch until all callers are queued
            return ("coalesced", 3600)

        # Launch first — it will start fetching and block on `release`.
        first = asyncio.create_task(cache.get_or_fetch("k", fetch, label="test"))
        await started.wait()

        # Now launch 4 more that must wait behind the per-key lock.
        others = [asyncio.create_task(cache.get_or_fetch("k", fetch, label="test")) for _ in range(4)]
        # Give the event loop a tick so `others` reach the lock.
        await asyncio.sleep(0)

        release.set()
        results = await asyncio.gather(first, *others)

        assert all(r == "coalesced" for r in results)
        assert calls == 1

    @pytest.mark.asyncio
    async def test_concurrent_different_keys_do_not_serialise(self):
        """Fetches for two distinct keys proceed in parallel — neither waits for the other."""
        import asyncio

        _KeyedTokenCache = self._import_cache()
        cache = _KeyedTokenCache()

        in_flight = 0
        max_in_flight = 0
        lock = asyncio.Lock()

        async def fetch_for(name):
            async def fetch():
                nonlocal in_flight, max_in_flight
                async with lock:
                    in_flight += 1
                    max_in_flight = max(max_in_flight, in_flight)
                await asyncio.sleep(0.02)
                async with lock:
                    in_flight -= 1
                return (f"tok-{name}", 3600)
            return fetch

        a_fetch = await fetch_for("A")
        b_fetch = await fetch_for("B")
        await asyncio.gather(
            cache.get_or_fetch("a", a_fetch, label="test"),
            cache.get_or_fetch("b", b_fetch, label="test"),
        )

        assert max_in_flight == 2, (
            f"Expected two fetches in flight concurrently, saw max={max_in_flight}. "
            "Per-key locking must not serialise unrelated keys."
        )

    @pytest.mark.asyncio
    async def test_evicts_lru_at_capacity(self):
        """When at max_entries, inserting a new key evicts the least-recently-used one."""
        _KeyedTokenCache = self._import_cache()
        cache = _KeyedTokenCache(max_entries=2)

        async def fetch_ok(val):
            async def fetch():
                return (val, 3600)
            return fetch

        await cache.get_or_fetch("a", await fetch_ok("tok-a"), label="test")
        await cache.get_or_fetch("b", await fetch_ok("tok-b"), label="test")
        # Insert third — "a" is oldest and should be evicted.
        await cache.get_or_fetch("c", await fetch_ok("tok-c"), label="test")

        assert "a" not in cache._entries  # type: ignore[attr-defined]
        assert "b" in cache._entries  # type: ignore[attr-defined]
        assert "c" in cache._entries  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_access_updates_recency(self):
        """Reading a cached entry marks it most-recently-used and delays its eviction."""
        _KeyedTokenCache = self._import_cache()
        cache = _KeyedTokenCache(max_entries=2)

        async def fetch_ok(val):
            async def fetch():
                return (val, 3600)
            return fetch

        await cache.get_or_fetch("a", await fetch_ok("tok-a"), label="test")
        await cache.get_or_fetch("b", await fetch_ok("tok-b"), label="test")
        # Touch "a" — it becomes most-recently-used.
        await cache.get_or_fetch("a", await fetch_ok("tok-a"), label="test")
        # Insert "c" — "b" is now oldest and must be evicted instead of "a".
        await cache.get_or_fetch("c", await fetch_ok("tok-c"), label="test")

        assert "a" in cache._entries  # type: ignore[attr-defined]
        assert "b" not in cache._entries  # type: ignore[attr-defined]
        assert "c" in cache._entries  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_fetch_exception_does_not_poison_cache(self):
        """A fetch() that raises propagates, does not store an entry, and does
        not block a subsequent successful fetch for the same key."""
        _KeyedTokenCache = self._import_cache()
        cache = _KeyedTokenCache()

        attempts = 0

        async def flaky_fetch():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("IdP is grumpy")
            return ("tok-recovered", 3600)

        with pytest.raises(RuntimeError, match="grumpy"):
            await cache.get_or_fetch("k", flaky_fetch, label="test")

        # Cache must be clean — no poisoned entry.
        assert "k" not in cache._entries  # type: ignore[attr-defined]

        # Next call succeeds and populates the cache.
        assert await cache.get_or_fetch("k", flaky_fetch, label="test") == "tok-recovered"
        assert "k" in cache._entries  # type: ignore[attr-defined]
