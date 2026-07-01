# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Pluggable backend token strategies for AAS MCP Server.

When the MCP server calls the AAS backend API, it must present a token that
the backend accepts. Three strategies are available:

- ForwardStrategy (default): forwards the upstream IdP token from FastMCP's
  request context. Works when the backend accepts the same token the MCP
  client received (same IdP, same audience).

- TokenExchangeStrategy: performs RFC 8693 token exchange — trades the
  upstream user token for a backend-scoped token. Works when the backend
  expects a token with a specific audience (its own client ID) and the IdP
  supports token exchange. User identity (sub) is preserved.

- NoneStrategy: adds no Authorization header. For public backends or backends
  that use other auth mechanisms (e.g. mTLS).

The strategy is selected by build_backend_token_provider() based on env vars:
- No BACKEND_AUTH_* vars set → ForwardStrategy
- BACKEND_AUTH_AUDIENCE set → TokenExchangeStrategy (auto-detected)
- BACKEND_AUTH_STRATEGY=<name> → explicit override
"""

import logging
import os
from typing import Protocol, runtime_checkable

import httpx
from fastmcp.server.dependencies import get_access_token

from .constants import (
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
    OAUTH_GRANT_TOKEN_EXCHANGE,
    OAUTH_TOKEN_TYPE_ACCESS_TOKEN,
    VALID_BACKEND_STRATEGIES,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class BackendTokenProvider(Protocol):
    """Protocol for backend token strategies.

    Implementations return the token string to use in the Authorization header,
    or None to omit the header entirely.
    """

    async def get_token(self) -> str | None:
        """Return the bearer token for the backend request, or None."""
        ...


class ForwardStrategy:
    """Forward the upstream user token from FastMCP's request context as-is."""

    async def get_token(self) -> str | None:
        access_token = get_access_token()
        if access_token is None:
            return None
        return access_token.token


class NoneStrategy:
    """Never add an Authorization header (public or mTLS-protected backends)."""

    async def get_token(self) -> str | None:
        return None


class TokenExchangeStrategy:
    """
    RFC 8693 Token Exchange — exchange the upstream user token for a
    backend-scoped token at the IdP's token endpoint.

    User identity is preserved in the issued token's ``sub`` claim.
    The issued token has ``aud`` matching the backend's client ID so the
    backend accepts it.

    A single ``httpx.AsyncClient`` is created at construction time and reused
    across all calls to avoid connection-churn overhead under load.

    Args:
        token_endpoint: Full URL of the IdP's token endpoint.
        client_id: Client ID for authenticating the exchange request (MCP server's ID).
        client_secret: Client secret for authenticating the exchange request.
        audience: The target audience — the backend's client ID.
        scope: Optional space-separated scopes to request from the backend token.
    """

    def __init__(
        self,
        token_endpoint: str,
        client_id: str,
        client_secret: str,
        audience: str,
        scope: str | None,
    ) -> None:
        self.token_endpoint = token_endpoint
        self.client_id = client_id
        self.client_secret = client_secret
        self.audience = audience
        self.scope = scope
        # Shared client — created once, reused per request to avoid connection churn.
        self._http_client = httpx.AsyncClient()

    async def get_token(self) -> str | None:
        access_token = get_access_token()
        if access_token is None:
            logger.debug("TokenExchangeStrategy: no upstream token — skipping exchange")
            return None

        upstream_token = access_token.token
        data: dict[str, str] = {
            "grant_type": OAUTH_GRANT_TOKEN_EXCHANGE,
            "subject_token": upstream_token,
            "subject_token_type": OAUTH_TOKEN_TYPE_ACCESS_TOKEN,
            "audience": self.audience,
        }
        if self.scope:
            data["scope"] = self.scope

        logger.debug(
            "TokenExchangeStrategy: exchanging token at %s for audience=%s scope=%s",
            self.token_endpoint,
            self.audience,
            self.scope or "<not set>",
        )

        try:
            response = await self._http_client.post(
                self.token_endpoint,
                data=data,
                auth=(self.client_id, self.client_secret),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Backend token exchange failed at {self.token_endpoint}: "
                f"HTTP {exc.response.status_code}. "
                f"Check BACKEND_AUTH_AUDIENCE, BACKEND_AUTH_CLIENT_ID, and that "
                f"the IdP is configured to allow token exchange for this client."
            ) from exc
        except httpx.RequestError as exc:
            raise RuntimeError(
                f"Backend token exchange request failed: {exc}. "
                f"Check BACKEND_AUTH_TOKEN_ENDPOINT ({self.token_endpoint}) is reachable."
            ) from exc

        try:
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(
                f"Backend token exchange at {self.token_endpoint} returned a non-JSON response "
                f"(content-type: {response.headers.get('content-type', '<unknown>')}). "
                f"Expected an OAuth 2.0 token response with 'access_token'."
            ) from exc

        if "access_token" not in payload:
            raise RuntimeError(
                f"Backend token exchange at {self.token_endpoint} succeeded (HTTP 200) but "
                f"the response is missing the 'access_token' field. "
                f"Check that the IdP is returning a valid OAuth 2.0 token response."
            )

        exchanged_token: str = payload["access_token"]
        logger.debug(
            "TokenExchangeStrategy: exchange succeeded, token length=%d",
            len(exchanged_token),
        )
        return exchanged_token

    async def aclose(self) -> None:
        """Close the shared httpx.AsyncClient and release the connection pool.

        Should be called on server shutdown. Wired into the FastMCP server
        lifespan by build_mcp_server so it is called automatically.
        """
        await self._http_client.aclose()

    async def __aenter__(self) -> "TokenExchangeStrategy":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


def _derive_token_endpoint_from_issuer(issuer_url: str) -> str:
    """Derive a token endpoint URL from an OIDC issuer URL.

    Uses the well-known convention: <issuer>/oauth2/token.
    This is a best-effort fallback — operators should set
    BACKEND_AUTH_TOKEN_ENDPOINT explicitly for non-standard IdPs.
    """
    base = issuer_url.rstrip("/")
    # Strip /.well-known/openid-configuration if present
    if base.endswith("openid-configuration"):
        base = base[: base.rfind("/.well-known")]
    return f"{base}/oauth2/token"


def build_backend_token_provider() -> BackendTokenProvider:
    """
    Build a backend token provider from environment variables.

    Selection logic:
    1. If BACKEND_AUTH_STRATEGY is set explicitly, use that strategy.
    2. Else if BACKEND_AUTH_AUDIENCE is set, auto-select token_exchange.
    3. Else use forward (preserve current behaviour).

    Raises ValueError with actionable messages for invalid configuration.
    """
    explicit_strategy = os.getenv(ENV_BACKEND_AUTH_STRATEGY, "").strip() or None
    audience = os.getenv(ENV_BACKEND_AUTH_AUDIENCE, "").strip() or None

    # Determine which strategy to use
    if explicit_strategy:
        if explicit_strategy not in VALID_BACKEND_STRATEGIES:
            raise ValueError(
                f"BACKEND_AUTH_STRATEGY={explicit_strategy!r} is not valid. "
                f"Choose one of: {', '.join(sorted(VALID_BACKEND_STRATEGIES))}."
            )
        strategy_name = explicit_strategy
    elif audience:
        strategy_name = BACKEND_STRATEGY_TOKEN_EXCHANGE
    else:
        strategy_name = BACKEND_STRATEGY_FORWARD

    if strategy_name == BACKEND_STRATEGY_NONE:
        logger.info("Backend auth strategy: none (no Authorization header)")
        return NoneStrategy()

    if strategy_name == BACKEND_STRATEGY_FORWARD:
        logger.info("Backend auth strategy: forward (upstream token forwarded as-is)")
        return ForwardStrategy()

    # token_exchange — validate and build
    if not audience:
        raise ValueError(
            "BACKEND_AUTH_AUDIENCE is required when BACKEND_AUTH_STRATEGY=token_exchange. "
            "Set it to the OAuth client ID of the AAS backend application."
        )

    # Token endpoint: explicit override > derive from issuer
    token_endpoint = os.getenv(ENV_BACKEND_AUTH_TOKEN_ENDPOINT, "").strip() or None
    if not token_endpoint:
        issuer_url = os.getenv(ENV_OAUTH_ISSUER_URL, "").strip() or None
        if not issuer_url:
            raise ValueError(
                "BACKEND_AUTH_TOKEN_ENDPOINT is not set and OAUTH_ISSUER_URL is also not set. "
                "Either set BACKEND_AUTH_TOKEN_ENDPOINT explicitly, or set OAUTH_ISSUER_URL "
                "so the token endpoint can be derived automatically."
            )
        token_endpoint = _derive_token_endpoint_from_issuer(issuer_url)
        logger.debug(
            "BACKEND_AUTH_TOKEN_ENDPOINT not set — derived from OAUTH_ISSUER_URL: %s",
            token_endpoint,
        )

    # Client credentials: BACKEND_AUTH_CLIENT_ID overrides OAUTH_CLIENT_ID
    client_id = (
        os.getenv(ENV_BACKEND_AUTH_CLIENT_ID, "").strip()
        or os.getenv(ENV_OAUTH_CLIENT_ID, "").strip()
        or None
    )
    client_secret = (
        os.getenv(ENV_BACKEND_AUTH_CLIENT_SECRET, "").strip()
        or os.getenv(ENV_OAUTH_CLIENT_SECRET, "").strip()
        or None
    )

    if not client_id:
        raise ValueError(
            "Token exchange requires a client ID. "
            "Set BACKEND_AUTH_CLIENT_ID (or OAUTH_CLIENT_ID as fallback)."
        )
    if not client_secret:
        raise ValueError(
            "Token exchange requires a client secret. "
            "Set BACKEND_AUTH_CLIENT_SECRET (or OAUTH_CLIENT_SECRET as fallback)."
        )

    scope = os.getenv(ENV_BACKEND_AUTH_SCOPE, "").strip() or None

    logger.info(
        "Backend auth strategy: token_exchange (RFC 8693) — endpoint=%s audience=%s scope=%s",
        token_endpoint,
        audience,
        scope or "<not set>",
    )

    return TokenExchangeStrategy(
        token_endpoint=token_endpoint,
        client_id=client_id,
        client_secret=client_secret,
        audience=audience,
        scope=scope,
    )
