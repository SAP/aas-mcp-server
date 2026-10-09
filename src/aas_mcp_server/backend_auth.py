# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Pluggable backend token strategies for AAS MCP Server.

When the MCP server calls the AAS backend API, it must present a token that
the backend accepts. Four strategies are available:

- ForwardStrategy (default): forwards the upstream IdP token from FastMCP's
  request context. Works when the backend accepts the same token the MCP
  client received (same IdP, same audience).

- TokenExchangeStrategy: performs RFC 8693 token exchange — trades the
  upstream user token for a backend-scoped token. Works when the backend
  expects a token with a specific audience (its own client ID) and the IdP
  supports token exchange. User identity (sub) is preserved. Exchanged
  tokens are cached in-memory per subject so the IdP is not hit on every
  backend request.

- ClientCredentialsStrategy: performs an OAuth 2.0 client credentials grant
  (RFC 6749 §4.4) — the MCP server authenticates as itself and obtains a
  backend token independent of any user session. Suitable for system-to-system
  deployments (e.g. stdio transport, batch jobs) or backends that trust the
  MCP server's own service identity. Caches the token until near expiry.

- NoneStrategy: adds no Authorization header. For public backends or backends
  that use other auth mechanisms (e.g. mTLS).

The strategy is selected by build_backend_token_provider() based on env vars:
- No BACKEND_AUTH_* vars set → ForwardStrategy
- BACKEND_AUTH_AUDIENCE set → TokenExchangeStrategy (auto-detected)
- BACKEND_AUTH_STRATEGY=<name> → explicit override (required for client_credentials)
"""

import asyncio
import hashlib
import logging
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol, runtime_checkable
from urllib.parse import urlparse, urlunparse

import httpx2
from fastmcp.server.dependencies import get_access_token

from .constants import (
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
    OAUTH_GRANT_CLIENT_CREDENTIALS,
    OAUTH_GRANT_TOKEN_EXCHANGE,
    OAUTH_TOKEN_TYPE_ACCESS_TOKEN,
    VALID_BACKEND_STRATEGIES,
)

logger = logging.getLogger(__name__)

# Refresh cached client_credentials tokens this many seconds before their
# stated expiry, to avoid a request being sent with a token that expires
# in-flight.
EXPIRY_BUFFER_SECONDS = 30

# Fallback lifetime when a client_credentials token response omits `expires_in`.
# Conservative: refresh often rather than reuse a token whose true expiry is unknown.
DEFAULT_TOKEN_LIFETIME_SECONDS = 300


# Default upper bound on the number of cached entries in a _KeyedTokenCache.
# Sized well above realistic concurrent-user counts on a single MCP server;
# safety cap only, not a user-facing knob.
DEFAULT_TOKEN_CACHE_MAX_ENTRIES = 1024


def _sanitize_endpoint_for_logging(url: str) -> str:
    """Return the form of a token endpoint URL that may appear in logs and errors.

    Keeps scheme, host, port and path. Drops userinfo, query and fragment: the
    endpoint comes from operator-set configuration and may carry a credential or
    a session parameter in those parts, and a log line lives much longer than
    the request that produced it.

    IPv6 hosts are re-wrapped in brackets. ``urlparse().hostname`` strips them,
    so reassembling the URL from ``hostname`` alone yields ``https://::1:8080/``.

    Raises ValueError when the URL has no scheme or host, or a port that is not
    an integer — the same conditions build_backend_token_provider() rejects.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port  # raises ValueError when the port is not an integer
    if not parsed.scheme or not host:
        raise ValueError(f"{url!r} is not a valid URL: scheme and host are required")
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port else host
    return urlunparse(parsed._replace(netloc=netloc, query="", fragment=""))


@runtime_checkable
class BackendTokenProvider(Protocol):
    """Protocol for backend token strategies.

    Implementations return the token string to use in the Authorization header,
    or None to omit the header entirely.
    """

    async def get_token(self) -> str | None:
        """Return the bearer token for the backend request, or None."""
        ...


@dataclass
class _CacheEntry:
    """One cached backend token with its monotonic-clock expiry."""

    token: str
    expires_at: float


class _KeyedTokenCache:
    """In-memory keyed token cache with per-key coalescing and LRU eviction.

    Both TokenExchangeStrategy (keyed per subject) and ClientCredentialsStrategy
    (single fixed key) delegate their caching here so the timing and locking
    behaviour cannot drift between them.

    Behaviour:

    - `get_or_fetch(key, fetch, label=...)` returns the cached token for `key`
      when the monotonic clock has not yet reached
      `expires_at - EXPIRY_BUFFER_SECONDS`. Otherwise it acquires a per-key
      lock (creating one on demand), re-checks under the lock, calls `fetch()`,
      stores the result, and returns the fetched token.
    - `fetch()` must return `(token, expires_in)`. When `expires_in` is not a
      positive integer, `DEFAULT_TOKEN_LIFETIME_SECONDS` is used instead.
      Callers therefore normalise `expires_in` at their layer if the raw IdP
      response carries anything odd (e.g. a string) — the cache treats any
      non-positive int the same way.
    - Concurrent misses under the same key coalesce into one `fetch()` call
      via the per-key lock; concurrent misses under different keys proceed in
      parallel.
    - An exception raised by `fetch()` propagates to the caller that made the
      call and does NOT store an entry — subsequent callers under the same
      key will retry independently.
    - The cache holds at most `max_entries`. Reaching an existing entry
      (whether cache hit or refresh) marks it most-recently-used. Inserting
      a new entry when at capacity evicts the least-recently-used entry.
      Locks for evicted keys are dropped at the same time.

    The class is private to this module. Test code reaches into `_entries` for
    verification of internal state.
    """

    def __init__(self, max_entries: int = DEFAULT_TOKEN_CACHE_MAX_ENTRIES) -> None:
        self._entries: "OrderedDict[str, _CacheEntry]" = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}
        self._max_entries = max_entries

    def _lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def get_or_fetch(
        self,
        key: str,
        fetch: Callable[[], Awaitable[tuple[str, int]]],
        *,
        label: str,
    ) -> str:
        # Fast path: cache hit outside the buffer window. No lock needed —
        # dict reads are atomic and a concurrent writer only races us to a
        # newer value, which is still correct to return here.
        entry = self._entries.get(key)
        now = time.monotonic()
        if entry is not None and now < entry.expires_at - EXPIRY_BUFFER_SECONDS:
            self._entries.move_to_end(key)
            logger.debug(
                "%s: reusing cached token (%.0fs until refresh)",
                label,
                entry.expires_at - EXPIRY_BUFFER_SECONDS - now,
            )
            return entry.token

        # Slow path: fetch under the per-key lock so concurrent misses coalesce.
        lock = self._lock_for(key)
        async with lock:
            # Another coroutine may have populated the entry while we waited.
            entry = self._entries.get(key)
            now = time.monotonic()
            if entry is not None and now < entry.expires_at - EXPIRY_BUFFER_SECONDS:
                self._entries.move_to_end(key)
                logger.debug(
                    "%s: reusing cached token (%.0fs until refresh)",
                    label,
                    entry.expires_at - EXPIRY_BUFFER_SECONDS - now,
                )
                return entry.token

            logger.debug("%s: fetching new token", label)
            token, expires_in = await fetch()
            if not isinstance(expires_in, int) or expires_in <= 0:
                expires_in = DEFAULT_TOKEN_LIFETIME_SECONDS

            self._entries[key] = _CacheEntry(
                token=token,
                expires_at=time.monotonic() + expires_in,
            )
            self._entries.move_to_end(key)
            self._evict_if_over_capacity()

            logger.debug(
                "%s: token acquired, length=%d expires_in=%ds",
                label,
                len(token),
                expires_in,
            )
            return token

    def _evict_if_over_capacity(self) -> None:
        """Drop least-recently-used entries (and their locks) until under cap."""
        while len(self._entries) > self._max_entries:
            evicted_key, _ = self._entries.popitem(last=False)
            self._locks.pop(evicted_key, None)


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

    Exchanged tokens are cached in-memory per subject, keyed by a SHA-256
    hex digest of the upstream access token. Two requests carrying the same
    upstream token share one cached exchange; two requests carrying different
    upstream tokens NEVER share a cache entry. The IdP is not hit on every
    backend request; refreshes happen once a cached entry falls inside the
    ``EXPIRY_BUFFER_SECONDS`` window. Concurrent requests for the same
    subject coalesce into a single exchange.

    A single ``httpx2.AsyncClient`` is created at construction time and reused
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
        # Sanitized once here so that no log line or error message below has to
        # remember to do it. Also rejects an endpoint without scheme or host.
        self._safe_endpoint = _sanitize_endpoint_for_logging(token_endpoint)
        self.client_id = client_id
        self.client_secret = client_secret
        self.audience = audience
        self.scope = scope
        # Shared client — created once, reused per request to avoid connection churn.
        self._http_client = httpx2.AsyncClient()
        # Per-subject cache. Independent from any other strategy's cache.
        self._cache = _KeyedTokenCache()

    async def get_token(self) -> str | None:
        access_token = get_access_token()
        if access_token is None:
            logger.debug("TokenExchangeStrategy: no upstream token — skipping exchange")
            return None

        upstream_token = access_token.token
        # SHA-256 of the raw upstream token is a stable, non-revealing per-subject key.
        # Storing the hash — not the token itself — keeps the credential out of the
        # cache-key memory footprint. A rotated upstream token yields a new key and
        # forces re-exchange, which is what we want: the old exchanged token was
        # tied to the old subject token's lifetime anyway.
        cache_key = hashlib.sha256(upstream_token.encode("utf-8")).hexdigest()

        return await self._cache.get_or_fetch(
            cache_key,
            lambda: self._exchange(upstream_token),
            label="TokenExchangeStrategy",
        )

    async def _exchange(self, upstream_token: str) -> tuple[str, int]:
        """Perform one RFC 8693 exchange and return (token, expires_in).

        Raises ``RuntimeError`` with an actionable message on any IdP failure
        or malformed response. Messages are unchanged from the pre-cache
        version to preserve the existing behavioural contract.
        """
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
            self._safe_endpoint,
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
        except httpx2.HTTPStatusError as exc:
            raise RuntimeError(
                f"Backend token exchange failed at {self._safe_endpoint}: "
                f"HTTP {exc.response.status_code}. "
                f"Check BACKEND_AUTH_AUDIENCE, BACKEND_AUTH_CLIENT_ID, and that "
                f"the IdP is configured to allow token exchange for this client."
            ) from exc
        except httpx2.RequestError as exc:
            raise RuntimeError(
                f"Backend token exchange request failed: {exc}. "
                f"Check BACKEND_AUTH_TOKEN_ENDPOINT ({self._safe_endpoint}) is reachable."
            ) from exc

        try:
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(
                f"Backend token exchange at {self._safe_endpoint} returned a non-JSON response "
                f"(content-type: {response.headers.get('content-type', '<unknown>')}). "
                f"Expected an OAuth 2.0 token response with 'access_token'."
            ) from exc

        if "access_token" not in payload:
            raise RuntimeError(
                f"Backend token exchange at {self._safe_endpoint} succeeded (HTTP 200) but "
                f"the response is missing the 'access_token' field. "
                f"Check that the IdP is returning a valid OAuth 2.0 token response."
            )

        exchanged_token: str = payload["access_token"]
        expires_in_raw = payload.get("expires_in")
        try:
            expires_in = int(expires_in_raw) if expires_in_raw is not None else DEFAULT_TOKEN_LIFETIME_SECONDS
        except (TypeError, ValueError):
            expires_in = DEFAULT_TOKEN_LIFETIME_SECONDS
        if expires_in <= 0:
            expires_in = DEFAULT_TOKEN_LIFETIME_SECONDS

        logger.debug(
            "TokenExchangeStrategy: exchange succeeded, token length=%d expires_in=%ds",
            len(exchanged_token),
            expires_in,
        )
        return exchanged_token, expires_in

    async def aclose(self) -> None:
        """Close the shared httpx2.AsyncClient and release the connection pool.

        Should be called on server shutdown. Wired into the FastMCP server
        lifespan by build_mcp_server so it is called automatically.
        """
        await self._http_client.aclose()

    async def __aenter__(self) -> "TokenExchangeStrategy":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


class ClientCredentialsStrategy:
    """
    OAuth 2.0 Client Credentials Grant (RFC 6749 §4.4).

    The MCP server authenticates as itself at the IdP's token endpoint and
    receives a backend-scoped access token that carries no user identity.
    Suitable for system-to-system flows where user context is absent or
    irrelevant, e.g. stdio transport, batch jobs, or backends that trust
    the MCP server's own service identity.

    The issued token is cached in-memory (via the shared ``_KeyedTokenCache``
    under a single fixed key) and reused across calls until it is about to
    expire (``EXPIRY_BUFFER_SECONDS`` before the stated ``expires_in``), so
    the IdP is not hit on every backend request. The cache coalesces
    concurrent refreshes into a single fetch.

    A single ``httpx2.AsyncClient`` is created at construction time and reused.

    Args:
        token_endpoint: Full URL of the IdP's token endpoint.
        client_id: Client ID authenticating this MCP server to the IdP.
        client_secret: Client secret for the same.
        scope: Optional space-separated scopes to request.
        audience: Optional audience (some IdPs — Auth0, SAP IAS — require it;
            spec-compliant IdPs treat it as unnecessary).
    """

    # Single-slot cache key — client credentials issues one identity-less token,
    # so a fixed key is correct.
    _CACHE_KEY = "__client_credentials__"

    def __init__(
        self,
        token_endpoint: str,
        client_id: str,
        client_secret: str,
        scope: str | None,
        audience: str | None,
    ) -> None:
        self.token_endpoint = token_endpoint
        # See TokenExchangeStrategy: sanitized once, used by every log and error.
        self._safe_endpoint = _sanitize_endpoint_for_logging(token_endpoint)
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.audience = audience
        self._http_client = httpx2.AsyncClient()
        self._cache = _KeyedTokenCache()

    async def get_token(self) -> str | None:
        return await self._cache.get_or_fetch(
            self._CACHE_KEY,
            self._fetch_token,
            label="ClientCredentialsStrategy",
        )

    async def _fetch_token(self) -> tuple[str, int]:
        """Perform the client-credentials token request and return (token, expires_in).

        Raises ``RuntimeError`` with an actionable message on any IdP failure
        or malformed response. Messages are unchanged from the pre-cache
        version to preserve the existing behavioural contract.
        """
        data: dict[str, str] = {"grant_type": OAUTH_GRANT_CLIENT_CREDENTIALS}
        if self.scope:
            data["scope"] = self.scope
        if self.audience:
            data["audience"] = self.audience

        logger.debug(
            "ClientCredentialsStrategy: fetching new token at %s scope=%s audience=%s",
            self._safe_endpoint,
            self.scope or "<not set>",
            self.audience or "<not set>",
        )

        try:
            response = await self._http_client.post(
                self.token_endpoint,
                data=data,
                auth=(self.client_id, self.client_secret),
            )
            response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            raise RuntimeError(
                f"Backend client_credentials token request failed at {self._safe_endpoint}: "
                f"HTTP {exc.response.status_code}. "
                f"Check BACKEND_AUTH_CLIENT_ID, BACKEND_AUTH_CLIENT_SECRET, and that the IdP "
                f"is configured to allow the client_credentials grant for this client."
            ) from exc
        except httpx2.RequestError as exc:
            raise RuntimeError(
                f"Backend client_credentials token request failed: {exc}. "
                f"Check BACKEND_AUTH_TOKEN_ENDPOINT ({self._safe_endpoint}) is reachable."
            ) from exc

        try:
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(
                f"Backend client_credentials token request at {self._safe_endpoint} returned "
                f"a non-JSON response (content-type: "
                f"{response.headers.get('content-type', '<unknown>')}). "
                f"Expected an OAuth 2.0 token response with 'access_token'."
            ) from exc

        if "access_token" not in payload:
            raise RuntimeError(
                f"Backend client_credentials token request at {self._safe_endpoint} succeeded "
                f"(HTTP 200) but the response is missing the 'access_token' field. "
                f"Check that the IdP is returning a valid OAuth 2.0 token response."
            )

        access_token: str = payload["access_token"]
        expires_in_raw = payload.get("expires_in")
        try:
            expires_in = int(expires_in_raw) if expires_in_raw is not None else DEFAULT_TOKEN_LIFETIME_SECONDS
        except (TypeError, ValueError):
            expires_in = DEFAULT_TOKEN_LIFETIME_SECONDS
        if expires_in <= 0:
            expires_in = DEFAULT_TOKEN_LIFETIME_SECONDS

        return access_token, expires_in

    async def aclose(self) -> None:
        """Close the shared httpx2.AsyncClient and release the connection pool."""
        await self._http_client.aclose()

    async def __aenter__(self) -> "ClientCredentialsStrategy":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()


def _discover_token_endpoint(issuer_url: str) -> str:
    """Discover the token endpoint from the OIDC provider's metadata document.

    Fetches <issuer>/.well-known/openid-configuration and returns the
    ``token_endpoint`` field, which is mandatory per RFC 8414 / OIDC Discovery.

    Raises ValueError with an actionable message if discovery fails or the
    field is absent — directing the operator to set BACKEND_AUTH_TOKEN_ENDPOINT.
    """
    base = issuer_url.rstrip("/")
    _well_known = "/.well-known/openid-configuration"
    if base.endswith(_well_known):
        base = base[: -len(_well_known)]
    elif base.endswith("/openid-configuration"):
        base = base[: -len("/openid-configuration")]
    discovery_url = f"{base}/.well-known/openid-configuration"

    try:
        response = httpx2.get(discovery_url, timeout=5.0)
        response.raise_for_status()
    except httpx2.HTTPStatusError as exc:
        raise ValueError(
            f"OIDC discovery at {discovery_url} returned HTTP {exc.response.status_code}. "
            f"Set BACKEND_AUTH_TOKEN_ENDPOINT explicitly to skip discovery."
        ) from exc
    except httpx2.RequestError as exc:
        raise ValueError(
            f"OIDC discovery request to {discovery_url} failed: {exc}. "
            f"Check that OAUTH_ISSUER_URL is reachable, or set BACKEND_AUTH_TOKEN_ENDPOINT explicitly."
        ) from exc

    try:
        metadata = response.json()
    except Exception as exc:
        raise ValueError(
            f"OIDC discovery at {discovery_url} returned a non-JSON response. "
            f"Set BACKEND_AUTH_TOKEN_ENDPOINT explicitly to skip discovery."
        ) from exc

    token_endpoint = metadata.get("token_endpoint")
    if not token_endpoint:
        raise ValueError(
            f"OIDC discovery document at {discovery_url} does not contain a 'token_endpoint' field. "
            f"Set BACKEND_AUTH_TOKEN_ENDPOINT explicitly."
        )

    logger.debug(
        "OIDC discovery: token_endpoint=%s (from %s)",
        _sanitize_endpoint_for_logging(token_endpoint),
        discovery_url,
    )
    return token_endpoint


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

    if strategy_name == BACKEND_STRATEGY_CLIENT_CREDENTIALS:
        # Token endpoint: explicit override > OIDC discovery from issuer
        cc_token_endpoint = os.getenv(ENV_BACKEND_AUTH_TOKEN_ENDPOINT, "").strip() or None
        if not cc_token_endpoint:
            cc_issuer_url = os.getenv(ENV_OAUTH_ISSUER_URL, "").strip() or None
            if not cc_issuer_url:
                raise ValueError(
                    "BACKEND_AUTH_TOKEN_ENDPOINT is not set and OAUTH_ISSUER_URL is also not set. "
                    "Either set BACKEND_AUTH_TOKEN_ENDPOINT explicitly, or set OAUTH_ISSUER_URL "
                    "so the token endpoint can be discovered from the OIDC metadata document."
                )
            cc_token_endpoint = _discover_token_endpoint(cc_issuer_url)
            logger.debug(
                "BACKEND_AUTH_TOKEN_ENDPOINT not set — discovered via OIDC metadata: %s",
                _sanitize_endpoint_for_logging(cc_token_endpoint),
            )

        cc_client_id = (
            os.getenv(ENV_BACKEND_AUTH_CLIENT_ID, "").strip()
            or os.getenv(ENV_OAUTH_CLIENT_ID, "").strip()
            or None
        )
        cc_client_secret = (
            os.getenv(ENV_BACKEND_AUTH_CLIENT_SECRET, "").strip()
            or os.getenv(ENV_OAUTH_CLIENT_SECRET, "").strip()
            or None
        )

        if not cc_client_id:
            raise ValueError(
                "Client credentials strategy requires a client ID. "
                "Set BACKEND_AUTH_CLIENT_ID (or OAUTH_CLIENT_ID as fallback)."
            )
        if not cc_client_secret:
            raise ValueError(
                "Client credentials strategy requires a client secret. "
                "Set BACKEND_AUTH_CLIENT_SECRET (or OAUTH_CLIENT_SECRET as fallback)."
            )

        cc_scope = os.getenv(ENV_BACKEND_AUTH_SCOPE, "").strip() or None
        cc_audience = os.getenv(ENV_BACKEND_AUTH_AUDIENCE, "").strip() or None

        try:
            _cc_safe_endpoint = _sanitize_endpoint_for_logging(cc_token_endpoint)
        except ValueError as exc:
            raise ValueError(
                f"BACKEND_AUTH_TOKEN_ENDPOINT={cc_token_endpoint!r} is not a valid URL. "
                "Expected a full URL with scheme and host, e.g. https://idp.example.com/oauth2/token."
            ) from exc

        logger.info(
            "Backend auth strategy: client_credentials (RFC 6749 §4.4) — endpoint=%s scope=%s audience=%s",
            _cc_safe_endpoint,
            cc_scope or "<not set>",
            cc_audience or "<not set>",
        )

        return ClientCredentialsStrategy(
            token_endpoint=cc_token_endpoint,
            client_id=cc_client_id,
            client_secret=cc_client_secret,
            scope=cc_scope,
            audience=cc_audience,
        )

    # token_exchange — validate and build
    if not audience:
        raise ValueError(
            "BACKEND_AUTH_AUDIENCE is required when BACKEND_AUTH_STRATEGY=token_exchange. "
            "Set it to the OAuth client ID of the AAS backend application."
        )

    # Token endpoint: explicit override > OIDC discovery from issuer
    token_endpoint = os.getenv(ENV_BACKEND_AUTH_TOKEN_ENDPOINT, "").strip() or None
    if not token_endpoint:
        issuer_url = os.getenv(ENV_OAUTH_ISSUER_URL, "").strip() or None
        if not issuer_url:
            raise ValueError(
                "BACKEND_AUTH_TOKEN_ENDPOINT is not set and OAUTH_ISSUER_URL is also not set. "
                "Either set BACKEND_AUTH_TOKEN_ENDPOINT explicitly, or set OAUTH_ISSUER_URL "
                "so the token endpoint can be discovered from the OIDC metadata document."
            )
        token_endpoint = _discover_token_endpoint(issuer_url)
        logger.debug(
            "BACKEND_AUTH_TOKEN_ENDPOINT not set — discovered via OIDC metadata: %s",
            _sanitize_endpoint_for_logging(token_endpoint),
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

    try:
        _safe_endpoint = _sanitize_endpoint_for_logging(token_endpoint)
    except ValueError as exc:
        raise ValueError(
            f"BACKEND_AUTH_TOKEN_ENDPOINT={token_endpoint!r} is not a valid URL. "
            "Expected a full URL with scheme and host, e.g. https://idp.example.com/oauth2/token."
        ) from exc

    logger.info(
        "Backend auth strategy: token_exchange (RFC 8693) — endpoint=%s audience=%s scope=%s",
        _safe_endpoint,
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
