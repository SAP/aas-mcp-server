# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
MCP server builder for AAS components.

This module orchestrates the complete MCP server construction pipeline:
1. Process OpenAPI specification (derive from config + apply overlay)
2. Curate the spec for safe tool generation (allowlist, read-only by default)
3. Build HTTP client (no static auth — OAuth token is forwarded per-request)
4. Build OIDCProxy auth provider if OAuth is configured
5. Generate FastMCP server from curated OpenAPI spec

## Auth provider (OIDCProxy)

When OAUTH_ISSUER_URL and OAUTH_CLIENT_ID are both set, the server acts as an
OAuth 2.1 Authorization Server via FastMCP's OIDCProxy. It exposes:

  /.well-known/oauth-authorization-server  (RFC 8414 — required by MCP clients)
  /authorize                               (proxied to upstream IdP)
  /token                                   (issues FastMCP-signed JWTs)
  /register                                (DCR for MCP clients)
  /auth/callback                           (upstream IdP redirect target)

This pattern works with any OIDC-compliant IdP regardless of whether that IdP
supports Dynamic Client Registration (SAP IAS, Keycloak, Azure AD, Okta, etc.).

OAUTH_SERVER_BASE_URL must be set when binding to a wildcard address (0.0.0.0)
so the server can advertise the correct public callback URL to the upstream IdP.
"""

import logging
import math
import os
from contextlib import asynccontextmanager
from functools import partial
from typing import AsyncIterator

from fastmcp import FastMCP
from fastmcp.server.auth import OIDCProxy
from fastmcp.server.auth.jwt_issuer import derive_jwt_key
from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware
from key_value.aio.protocols.key_value import AsyncKeyValueProtocol
from key_value.aio.stores.memory import MemoryStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from cryptography.fernet import Fernet

from .config import ComponentConfig
from .spec_processor import process_component_spec
from .schema_flattener import flatten_spec_schemas
from .backend_auth import BackendTokenProvider, build_backend_token_provider
from .http_client import build_async_client
from .tool_curation import curate_openapi_spec, prune_unused_schemas
from .logging import configure_logging
from .constants import (
    DEFAULT_LOG_LEVEL,
    DEFAULT_RATE_LIMIT_PER_MINUTE,
    LOCALHOST_ADDRESSES,
    SECONDS_PER_MINUTE,
    SERVER_NAME_FORMAT,
    WILDCARD_BIND_ADDRESSES,
    ENV_OAUTH_ISSUER_URL,
    ENV_OAUTH_CLIENT_ID,
    ENV_OAUTH_CLIENT_SECRET,
    ENV_OAUTH_JWT_SIGNING_KEY,
    ENV_OAUTH_AUDIENCE,
    ENV_OAUTH_REQUIRED_SCOPES,
    ENV_OAUTH_SERVER_BASE_URL,
    ENV_OAUTH_SESSION_STORE_URL,
    ENV_MCP_RATE_LIMIT_PER_MINUTE,
)

logger = logging.getLogger(__name__)

HTTP_TRANSPORTS = frozenset({"http", "sse", "streamable-http"})


@asynccontextmanager
async def _provider_lifespan(
    server: FastMCP,  # noqa: ARG001 — required by FastMCP lifespan protocol
    provider: BackendTokenProvider,
) -> AsyncIterator[None]:
    """Lifespan context manager that closes the backend token provider on shutdown.

    Only providers that implement ``aclose()`` (currently TokenExchangeStrategy)
    need cleanup; all others are no-ops.
    """
    try:
        yield
    finally:
        aclose = getattr(provider, "aclose", None)
        if callable(aclose):
            await aclose()


def _parse_positive_int(env_var: str, default: int) -> int:
    """
    Read an environment variable as a positive integer.

    Raises ValueError with an actionable message if the value is not a
    valid integer or is less than 1.
    """
    raw = os.getenv(env_var, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(
            f"Invalid value for {env_var}: {raw!r} is not an integer. "
            f"Provide a positive integer (default: {default})."
        )
    if value < 1:
        raise ValueError(
            f"Invalid value for {env_var}: {value} is not allowed. "
            f"Value must be >= 1 (default: {default})."
        )
    return value


def _parse_positive_float(env_var: str, default: float) -> float:
    """
    Read an environment variable as a positive finite float.

    Raises ValueError with an actionable message if the value is not a
    valid finite float or is not greater than 0. Explicitly rejects nan
    and inf which float() accepts but which produce undefined behaviour.
    """
    raw = os.getenv(env_var, str(default))
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(
            f"Invalid value for {env_var}: {raw!r} is not a number. "
            f"Provide a positive finite number (default: {default})."
        )
    if not math.isfinite(value) or value <= 0:
        raise ValueError(
            f"Invalid value for {env_var}: {value!r} is not allowed. "
            f"Value must be a positive finite number (default: {default})."
        )
    return value


OIDC_CONFIG_SUFFIX = "/.well-known/openid-configuration"


def _build_session_store(url: str, encryption_key: bytes) -> AsyncKeyValueProtocol:
    """Build an encrypted OAuth session store from a URL.

    Supported schemes:
    - redis:// / rediss://     → RedisStore  (requires aas-mcp-server[redis])
    - postgresql:// / postgres:// → PostgreSQLStore  (requires aas-mcp-server[postgresql])

    The store is wrapped with FernetEncryptionWrapper using the same key FastMCP
    would use for its default file store, so tokens are encrypted at rest regardless
    of backend. Raises ValueError for unrecognised schemes.
    """
    from urllib.parse import urlparse
    scheme = urlparse(url).scheme.lower()
    if scheme in ("redis", "rediss"):
        from key_value.aio.stores.redis import RedisStore  # type: ignore[import]
        # Pass ssl=True explicitly for rediss:// — key_value's URL parser omits it
        if scheme == "rediss":
            from redis.asyncio import Redis as _Redis  # type: ignore[import]
            parsed = urlparse(url)
            client = _Redis(
                host=parsed.hostname or "localhost",
                port=parsed.port or 6380,
                db=int(parsed.path.lstrip("/")) if parsed.path and parsed.path != "/" else 0,
                username=parsed.username,
                password=parsed.password,
                ssl=True,
                decode_responses=True,
            )
            raw_store = RedisStore(client=client)
        else:
            raw_store = RedisStore(url=url)
    elif scheme in ("postgresql", "postgres"):
        from key_value.aio.stores.postgresql import PostgreSQLStore  # type: ignore[import]
        raw_store = PostgreSQLStore(url=url)
    else:
        raise ValueError(
            f"OAUTH_SESSION_STORE_URL scheme {scheme!r} is not supported. "
            f"Use one of: redis://, rediss://, postgresql://. "
            f"Leave unset to use the default in-memory store."
        )

    return FernetEncryptionWrapper(
        key_value=raw_store,
        fernet=Fernet(key=encryption_key),
        raise_on_decryption_error=False,
    )


def build_auth_provider(
    host: str,
    port: int,
) -> OIDCProxy | None:
    """
    Build a FastMCP OIDCProxy from environment variables, or return None.

    Returns None when OAUTH_ISSUER_URL is not set (auth disabled).

    Raises ValueError with an actionable message when OAUTH_ISSUER_URL is set
    but OAUTH_CLIENT_ID is missing (required for OIDCProxy).

    OAUTH_ISSUER_URL accepts either the OIDC issuer base URL (e.g.
    https://tenant.accounts.ondemand.com) or the full OIDC configuration URL
    (e.g. https://tenant.accounts.ondemand.com/.well-known/openid-configuration).
    When the base URL form is provided, the suffix is appended automatically.
    """
    issuer_url = os.getenv(ENV_OAUTH_ISSUER_URL)
    if not issuer_url:
        return None

    client_id = (os.getenv(ENV_OAUTH_CLIENT_ID) or "").strip() or None
    if not client_id:
        raise ValueError(
            "OAUTH_ISSUER_URL is set but OAUTH_CLIENT_ID is not. "
            "OIDCProxy requires a client ID registered at the upstream IdP. "
            "Set OAUTH_CLIENT_ID to the client ID from your IdP application registration."
        )

    # Normalise to full OIDC configuration URL
    _issuer_normalized = issuer_url.strip().rstrip("/")
    config_url = (
        _issuer_normalized
        if _issuer_normalized.endswith(OIDC_CONFIG_SUFFIX.lstrip("/"))
        or _issuer_normalized.endswith("openid-configuration")
        else _issuer_normalized + OIDC_CONFIG_SUFFIX
    )

    client_secret = os.getenv(ENV_OAUTH_CLIENT_SECRET)
    jwt_signing_key = os.getenv(ENV_OAUTH_JWT_SIGNING_KEY)
    audience = os.getenv(ENV_OAUTH_AUDIENCE)

    scopes_raw = os.getenv(ENV_OAUTH_REQUIRED_SCOPES)
    required_scopes: list[str] | None = None
    if scopes_raw:
        required_scopes = [s.strip() for s in scopes_raw.split(",") if s.strip()]

    # Derive the public base URL (used for /auth/callback redirect URI and RFC 8414 metadata)
    explicit_base = os.getenv(ENV_OAUTH_SERVER_BASE_URL)

    if not explicit_base and host in WILDCARD_BIND_ADDRESSES:
        raise ValueError(
            f"OAuth is enabled and MCP_HOST is a wildcard address ({host}) but "
            "OAUTH_SERVER_BASE_URL is not set. OIDCProxy needs a reachable public URL "
            "to register the /auth/callback redirect URI with the upstream IdP. "
            "Set OAUTH_SERVER_BASE_URL to the public-facing URL of this server, "
            "e.g. OAUTH_SERVER_BASE_URL=http://localhost:8000"
        )

    if explicit_base:
        server_base_url = explicit_base
    elif host in LOCALHOST_ADDRESSES:
        formatted_host = f"[{host}]" if ":" in host else host
        server_base_url = f"http://{formatted_host}:{port}"
    else:
        formatted_host = f"[{host}]" if ":" in host else host
        server_base_url = f"https://{formatted_host}:{port}"

    # Session store: use external store if URL provided, else default to MemoryStore.
    # Both paths use the same encryption key FastMCP would derive for its default file
    # store, so tokens are always encrypted at rest regardless of backend.
    # For multi-replica deployments use OAUTH_SESSION_STORE_URL=redis://... or
    # postgresql://... (with sticky sessions as fallback).
    #
    # We derive the encryption key here — before OIDCProxy — using the same logic
    # FastMCP would apply internally, so key rotation causes cache-misses (re-auth)
    # rather than decryption errors.
    _jwt_key_material = jwt_signing_key or client_secret
    if _jwt_key_material:
        _storage_encryption_key = derive_jwt_key(
            high_entropy_material=_jwt_key_material
            if isinstance(_jwt_key_material, str)
            else _jwt_key_material.decode(),
            salt="fastmcp-storage-encryption-key",
        )
    else:
        # No key material available yet — OIDCProxy will derive it internally.
        # Fall back to None so OIDCProxy manages the store with its own key.
        _storage_encryption_key = None

    store_url = os.getenv(ENV_OAUTH_SESSION_STORE_URL)
    if store_url:
        if _storage_encryption_key is None:
            raise ValueError(
                "OAUTH_SESSION_STORE_URL requires either OAUTH_CLIENT_SECRET or "
                "OAUTH_JWT_SIGNING_KEY to be set so the store can encrypt tokens at rest."
            )
        client_storage: AsyncKeyValueProtocol = _build_session_store(
            store_url, _storage_encryption_key
        )
        _store_label = f"{type(client_storage).__name__}({store_url.split('://')[0]}://...)"
    else:
        client_storage = MemoryStore()
        _store_label = "MemoryStore"

    logger.info(
        "OAuth 2.1 OIDCProxy enabled: config_url=%s, client_id=%s, "
        "audience=%s, scopes=%s, server_base_url=%s, session_store=%s",
        config_url,
        client_id,
        audience or "<not set>",
        required_scopes or "<not set>",
        server_base_url,
        _store_label,
    )

    # Always send "openid" so the IdP returns an id_token / OIDC identity claims.
    # Append any operator-configured scopes after it, deduplicated.
    extra_authorize_params: dict[str, str] = {
        "scope": " ".join(dict.fromkeys(["openid", *(required_scopes or [])]))
    }

    return OIDCProxy(
        config_url=config_url,
        client_id=client_id,
        client_secret=client_secret,
        audience=audience,
        required_scopes=None,  # Don't enforce scopes on FastMCP tokens — MCP clients
                               # register via DCR with no scopes.
        base_url=server_base_url,
        jwt_signing_key=jwt_signing_key,
        forward_resource=False,  # Disable RFC 8707 resource param — rejected by SAP IAS
                                 # and unnecessary for non-resource-indicator IdPs.
        require_authorization_consent="external",  # Consent handled by upstream IdP
        client_storage=client_storage,
        extra_authorize_params=extra_authorize_params,
    )


def build_mcp_server(
    component_config: ComponentConfig,
    base_url: str,
    enable_writes: bool,
    log_level: str = DEFAULT_LOG_LEVEL,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    """
    Build and configure an MCP server for AAS components.

    Args:
        component_config: Component configuration from config.yaml
        base_url: Base URL of the AAS backend server
        enable_writes: Whether to enable write operations (POST/PUT/PATCH/DELETE)
        log_level: Logging level (default: INFO)
        transport: MCP transport type ('stdio', 'http', 'sse', etc.)
        host: Host the server will bind to (used for TLS warning and base URL)
        port: Port the server will bind to (used for base URL construction)

    Returns:
        Configured FastMCP server instance
    """
    configure_logging(log_level, transport=transport)

    # Warn when OAuth is active over plain HTTP on a non-localhost bind address
    if os.getenv(ENV_OAUTH_ISSUER_URL) and transport in HTTP_TRANSPORTS:
        if host not in LOCALHOST_ADDRESSES:
            logger.warning(
                "OAuth is enabled but TLS termination cannot be verified. "
                "All authorization endpoints MUST be served over HTTPS in "
                "production. Ensure a TLS-terminating reverse proxy is in place."
            )

    # When OAUTH_REQUIRED_SCOPES is set, inform operators that scope enforcement is
    # delegated to the upstream IdP's /authorize step — not applied per-request on
    # FastMCP-issued tokens. This is intentional: DCR clients register without scopes
    # so FastMCP tokens carry an empty scope list; enforcing required_scopes on the
    # JWTVerifier would reject every MCP client request. The IdP only issues an
    # authorization code to users who hold the requested scopes, which is the correct
    # enforcement point for this architecture.
    scopes_raw = os.getenv(ENV_OAUTH_REQUIRED_SCOPES)
    if scopes_raw and scopes_raw.strip():
        logger.warning(
            "OAUTH_REQUIRED_SCOPES is set (%s). "
            "Scope enforcement is per-authorization-flow only, not per-request: "
            "these scopes are requested from the upstream IdP during the PKCE "
            "authorization flow and the IdP will only issue an authorization code "
            "to users who hold them. FastMCP-issued tokens are NOT re-validated "
            "for scopes on every request because MCP clients register via DCR "
            "without declaring scopes, so FastMCP tokens carry an empty scope list. "
            "Operators upgrading from a JWTVerifier-based setup should note that "
            "per-request scope validation no longer occurs at the MCP boundary.",
            scopes_raw.strip(),
        )

    # Process spec according to config (derive + apply overlay)
    spec = process_component_spec(component_config)

    # Resolve $refs and flatten allOf so FastMCP sees plain schemas
    spec = flatten_spec_schemas(spec)

    # Curate tool surface area (rename, filter, readonly-by-default)
    curated = curate_openapi_spec(
        spec, enable_writes=enable_writes, curation_settings=component_config.curation
    )

    # Remove schemas no longer reachable from the curated paths
    curated = prune_unused_schemas(curated)

    # Build backend token provider (selects forward/token_exchange/none from env vars)
    backend_token_provider = build_backend_token_provider()

    # Build HTTP client with the selected backend token strategy
    client = build_async_client(base_url=base_url, backend_token_provider=backend_token_provider)

    # Build auth provider (None when OAuth not configured)
    auth_provider = build_auth_provider(host=host, port=port)

    # Configure rate limiting (convert per-minute to per-second for token bucket)
    rate_limit = _parse_positive_int(
        ENV_MCP_RATE_LIMIT_PER_MINUTE, DEFAULT_RATE_LIMIT_PER_MINUTE
    )
    rate_limiter = RateLimitingMiddleware(
        max_requests_per_second=rate_limit / SECONDS_PER_MINUTE,
        burst_capacity=rate_limit,
    )

    # Generate MCP server from OpenAPI.
    # mask_error_details=True prevents internal backend error messages (stack
    # traces, AAS backend URLs, internal hostnames) from leaking to MCP clients.
    #
    # lifespan: closes the backend token provider's connection pool on shutdown.
    # Only TokenExchangeStrategy holds a long-lived httpx.AsyncClient that needs
    # explicit cleanup; ForwardStrategy and NoneStrategy are stateless.
    mcp = FastMCP.from_openapi(
        openapi_spec=curated,
        client=client,
        name=SERVER_NAME_FORMAT.format(component_name=component_config.component_name),
        auth=auth_provider,
        middleware=[rate_limiter],
        mask_error_details=True,
        lifespan=partial(_provider_lifespan, provider=backend_token_provider),
    )

    return mcp
