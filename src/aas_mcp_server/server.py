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
from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware
from key_value.aio.stores.memory import MemoryStore

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

    logger.info(
        "OAuth 2.1 OIDCProxy enabled: config_url=%s, client_id=%s, "
        "audience=%s, scopes=%s, server_base_url=%s",
        config_url,
        client_id,
        audience or "<not set>",
        required_scopes or "<not set>",
        server_base_url,
    )

    # Build extra params to send to upstream IdP during authorization.
    # Request "openid" scope by default so the IdP returns an id_token.
    # If OAUTH_REQUIRED_SCOPES is set, request those specific scopes (useful for
    # single-tenant deployments). If not set, omit the scope parameter entirely
    # so the IdP grants all scopes the user is authorized for (better for
    # multi-tenant scenarios where scope names include tenant identifiers).
    # Do NOT enforce scopes on FastMCP-issued tokens (required_scopes=None)
    # because MCP clients (Claude CLI, OpenCode) register via DCR with no
    # scopes, so FastMCP tokens will have an empty scope list.
    extra_authorize_params: dict[str, str] = {}
    if required_scopes:
        # User explicitly configured scopes — request openid + those scopes
        extra_authorize_params["scope"] = " ".join(
            dict.fromkeys(["openid", *required_scopes])
        )
    # If required_scopes is not set, don't send scope parameter at all.
    # By OAuth spec, the IdP will grant all scopes the user is authorized for.

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
        client_storage=MemoryStore(),  # Avoid disk storage — container home dir may not exist
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
