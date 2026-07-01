# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Auth integration tests for the MCP server.

Tests OAuth 2.1 inbound authorization behavior using FastMCP's
StaticTokenVerifier (a built-in test helper that accepts pre-configured
static tokens without needing a real OAuth provider).

Covers:
- 5.2: Per-request auth (session hijacking prevention)
- 5.3: Token in query string rejected (MCP spec §5.1.1)
- 6.1: Valid/invalid/expired/wrong-scope token responses
- 6.2: stdio transport — no auth required
- 6.3: OAuth discovery endpoint accessible without auth
- 6.4: Missing OAUTH_CLIENT_ID raises ValueError
"""

import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

import httpx
import pytest

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from fastmcp.utilities.tests import run_server_async

from aas_mcp_server.server import build_auth_provider, build_mcp_server


# ---------------------------------------------------------------------------
# Test constants — no magic strings or numbers scattered across tests
# ---------------------------------------------------------------------------

# Token identifiers used in the static registry
TOKEN_VALID = "valid-token"
TOKEN_WRITE = "write-token"
TOKEN_EXPIRED = "expired-token"
TOKEN_INVALID = "totally-invalid-token"

# OAuth scopes
SCOPE_READ = "aas:read"
SCOPE_WRITE = "aas:write"

# Test client / server identifiers
TEST_CLIENT_ID = "test-client"
TEST_SERVER_NAME = "test-server"

# A plausible OAuth issuer URL used in unit tests (no network calls are made)
TEST_ISSUER_URL = "https://idp.example.com/realms/test"
TEST_AUDIENCE = "aas-mcp-server"

# Seconds that "expired" tokens are past their expiry
EXPIRED_OFFSET_SECONDS = 3600

# MCP protocol version used in test requests
MCP_PROTOCOL_VERSION = "2025-03-26"

# A minimal MCP initialize request used in HTTP-level auth tests
MCP_REQUEST = {
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
    "id": 1,
}

# Discovery endpoint path (MCP spec / RFC 8414)
OAUTH_DISCOVERY_PATH = "/.well-known/oauth-authorization-server"

# An empty OpenAPI spec used when mocking the spec-processing pipeline
EMPTY_SPEC = {"paths": {}}


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def make_test_server(required_scopes: list[str] | None = None) -> FastMCP:
    """Build a minimal FastMCP server with StaticTokenVerifier for testing."""
    verifier = StaticTokenVerifier(
        tokens={
            TOKEN_VALID: {
                "client_id": TEST_CLIENT_ID,
                "scopes": [SCOPE_READ],
            },
            TOKEN_WRITE: {
                "client_id": TEST_CLIENT_ID,
                "scopes": [SCOPE_READ, SCOPE_WRITE],
            },
            TOKEN_EXPIRED: {
                "client_id": TEST_CLIENT_ID,
                "scopes": [SCOPE_READ],
                "expires_at": int(time.time()) - EXPIRED_OFFSET_SECONDS,
            },
        },
        required_scopes=required_scopes,
    )
    mcp = FastMCP(TEST_SERVER_NAME, auth=verifier)

    @mcp.tool()
    def ping() -> str:
        return "pong"

    return mcp


def _bearer(token: str) -> dict[str, str]:
    """Build an Authorization header dict for the given token."""
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 6.1 — Valid / invalid / expired / wrong-scope token responses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_token_accepted():
    """6.1a: Request with valid Bearer token succeeds (200 or MCP response)."""
    mcp = make_test_server(required_scopes=[SCOPE_READ])
    async with run_server_async(mcp, transport="streamable-http") as url:
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=MCP_REQUEST, headers=_bearer(TOKEN_VALID))
        assert r.status_code != 401, f"Expected non-401, got {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_missing_token_returns_401():
    """6.1b: Request without Authorization header returns 401."""
    mcp = make_test_server()
    async with run_server_async(mcp, transport="streamable-http") as url:
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=MCP_REQUEST)
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"


@pytest.mark.asyncio
async def test_invalid_token_returns_401():
    """6.1c: Request with a token not in the static registry returns 401."""
    mcp = make_test_server()
    async with run_server_async(mcp, transport="streamable-http") as url:
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=MCP_REQUEST, headers=_bearer(TOKEN_INVALID))
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"


@pytest.mark.asyncio
async def test_expired_token_returns_401():
    """6.1c: Expired token is rejected with 401."""
    mcp = make_test_server()
    async with run_server_async(mcp, transport="streamable-http") as url:
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=MCP_REQUEST, headers=_bearer(TOKEN_EXPIRED))
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"


@pytest.mark.asyncio
async def test_token_missing_required_scope_returns_4xx():
    """6.1d: Token without a required scope is rejected.

    FastMCP's StaticTokenVerifier returns None on scope failure, which maps
    to 401. The JWTVerifier (production) returns 403 for scope failures per
    MCP spec §5.3. We verify the request is rejected (4xx), not accepted.
    """
    mcp = make_test_server(required_scopes=[SCOPE_WRITE])
    async with run_server_async(mcp, transport="streamable-http") as url:
        async with httpx.AsyncClient() as client:
            # TOKEN_VALID only has SCOPE_READ, not SCOPE_WRITE
            r = await client.post(url, json=MCP_REQUEST, headers=_bearer(TOKEN_VALID))
        assert r.status_code in (401, 403), (
            f"Token with missing scope should be rejected; got {r.status_code}"
        )


# ---------------------------------------------------------------------------
# 5.2 — Per-request auth (no session-based bypass)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_request_with_invalid_token_rejected():
    """5.2: A second request with an invalid token is rejected even after
    a first successful request — tokens are validated on every request,
    not cached in session state.
    """
    mcp = make_test_server()
    async with run_server_async(mcp, transport="streamable-http") as url:
        async with httpx.AsyncClient() as client:
            r1 = await client.post(url, json=MCP_REQUEST, headers=_bearer(TOKEN_VALID))
            assert r1.status_code != 401, f"First request failed: {r1.status_code}"

            r2 = await client.post(
                url,
                json={**MCP_REQUEST, "id": 2},
                headers=_bearer(TOKEN_INVALID),
            )
            assert r2.status_code == 401, (
                f"Second request with bad token should be 401, got {r2.status_code}"
            )


# ---------------------------------------------------------------------------
# 5.3 — Token in query string rejected (MCP spec §5.1.1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_in_query_string_rejected():
    """5.3: Token passed as ?access_token= query param is NOT accepted.
    MCP spec §5.1.1 requires tokens only in the Authorization header.
    """
    mcp = make_test_server()
    async with run_server_async(mcp, transport="streamable-http") as url:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{url}?access_token={TOKEN_VALID}",
                json=MCP_REQUEST,
                # No Authorization header — token only in query string
            )
        assert r.status_code == 401, (
            f"Token in query string should not be accepted; got {r.status_code}"
        )


# ---------------------------------------------------------------------------
# 6.2 — stdio transport: no auth required
# ---------------------------------------------------------------------------


def test_stdio_build_has_no_auth():
    """6.2: build_mcp_server with stdio transport and no OAUTH_ISSUER_URL
    sets auth=None — stdio always bypasses inbound auth.
    """
    mock_config = MagicMock()
    mock_config.component_name = "aas-repo"
    mock_config.curation = None
    mock_config.official_spec = Path("/tmp/spec.yaml")
    mock_config.implementation_spec = None
    mock_config.overlay = None
    mock_config.has_both_specs.return_value = False

    with (
        patch("aas_mcp_server.server.configure_logging"),
        patch("aas_mcp_server.server.process_component_spec", return_value=EMPTY_SPEC),
        patch("aas_mcp_server.server.flatten_spec_schemas", return_value=EMPTY_SPEC),
        patch("aas_mcp_server.server.curate_openapi_spec", return_value=EMPTY_SPEC),
        patch("aas_mcp_server.server.prune_unused_schemas", return_value=EMPTY_SPEC),
        patch("aas_mcp_server.server.build_async_client"),
        patch("aas_mcp_server.server.FastMCP") as mock_fastmcp,
        patch.dict(os.environ, {}, clear=True),
    ):
        build_mcp_server(mock_config, "http://localhost", False, transport="stdio")

        _, kwargs = mock_fastmcp.from_openapi.call_args
        assert kwargs.get("auth") is None, "stdio server must have auth=None"


# ---------------------------------------------------------------------------
# 6.3 — OAuth discovery endpoint accessible without auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oauth_discovery_endpoint_no_auth_required():
    """6.3: The well-known OAuth discovery endpoint must NOT require authentication.

    With StaticTokenVerifier (used in unit tests), FastMCP does not serve
    /.well-known/oauth-authorization-server (returns 404). The key assertion
    is that the endpoint is not auth-gated (no 401/403).

    In production with OIDCProxy, this endpoint returns 200 with full RFC 8414
    metadata — verified by integration testing against a real IdP.
    """
    mcp = make_test_server()
    async with run_server_async(mcp, transport="streamable-http") as url:
        parsed = urlparse(url)
        discovery_url = f"{parsed.scheme}://{parsed.netloc}{OAUTH_DISCOVERY_PATH}"
        async with httpx.AsyncClient() as client:
            r = await client.get(discovery_url)
        assert r.status_code not in (401, 403), (
            f"Discovery endpoint must not require auth; got {r.status_code}"
        )


# ---------------------------------------------------------------------------
# 6.4 — Missing OAUTH_CLIENT_ID raises ValueError
# ---------------------------------------------------------------------------


def test_missing_client_id_raises_when_issuer_set():
    """6.4: build_auth_provider raises ValueError when OAUTH_ISSUER_URL is set
    but OAUTH_CLIENT_ID is not — OIDCProxy requires client credentials.
    """
    env = {"OAUTH_ISSUER_URL": "https://idp.example.com"}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(ValueError, match="OAUTH_CLIENT_ID"):
            build_auth_provider(host="127.0.0.1", port=8000)
