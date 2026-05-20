# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
MCP server builder for AAS components.

This module orchestrates the complete MCP server construction pipeline:
1. Process OpenAPI specification (derive from config + apply overlay)
2. Curate the spec for safe tool generation (allowlist, read-only by default)
3. Build HTTP client (no static auth — OAuth token is forwarded per-request)
4. Build FastMCP RemoteAuthProvider if OAuth is configured
5. Generate FastMCP server from curated OpenAPI spec

## Audience enforcement

OAUTH_AUDIENCE is optional for local development (MCP_HOST is localhost/127.0.0.1/::1)
but becomes a hard startup failure when the server is bound to a non-localhost address.
This is automatic — no separate profile flag is needed. The bind address itself is the
reliable signal: a non-local HTTP deployment is a network-accessible service, which is
exactly the context where token passthrough attacks are a real risk.
"""

import logging
import os

from fastmcp import FastMCP
from fastmcp.server.auth import JWTVerifier, RemoteAuthProvider
from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware
from pydantic import AnyHttpUrl

from .config import ComponentConfig
from .spec_processor import process_component_spec
from .schema_flattener import flatten_spec_schemas
from .http_client import build_async_client
from .tool_curation import curate_openapi_spec, prune_unused_schemas
from .logging import configure_logging
from .constants import (
    DEFAULT_LOG_LEVEL,
    DEFAULT_RATE_LIMIT_PER_MINUTE,
    JWKS_WELL_KNOWN_PATH,
    LOCALHOST_ADDRESSES,
    SECONDS_PER_MINUTE,
    SERVER_NAME_FORMAT,
    ENV_OAUTH_ISSUER_URL,
    ENV_OAUTH_AUDIENCE,
    ENV_OAUTH_REQUIRED_SCOPES,
    ENV_OAUTH_JWKS_URI,
    ENV_OAUTH_SERVER_BASE_URL,
    ENV_MCP_RATE_LIMIT_PER_MINUTE,
)

logger = logging.getLogger(__name__)

HTTP_TRANSPORTS = frozenset({"http", "sse", "streamable-http"})
SCOPES_DELIMITER = ","


def _build_jwt_verifier_from_env(*, local_dev: bool = True) -> JWTVerifier | None:
    """
    Build a JWTVerifier from environment variables, or return None.

    Shared implementation used by both build_jwt_verifier() and
    build_auth_provider(). Handles audience enforcement:

    - local_dev=True: OAUTH_AUDIENCE is optional — WARNING if missing.
      Only used when the server is bound to a localhost address AND
      OAUTH_SERVER_BASE_URL is not set. This covers genuine local development
      where the server is not reachable from outside the machine.

    - local_dev=False (default for any network-accessible deployment):
      OAUTH_AUDIENCE is mandatory — raises ValueError if missing.
      This covers: non-localhost bind address, or OAUTH_SERVER_BASE_URL set
      (operator declared a public URL, even if bind is localhost e.g. behind
      a reverse proxy). Without audience validation, tokens intended for other
      services are accepted — token passthrough risk.

    Returns None when OAUTH_ISSUER_URL is not set.
    """
    issuer_url = os.getenv(ENV_OAUTH_ISSUER_URL)
    if not issuer_url:
        return None

    audience = os.getenv(ENV_OAUTH_AUDIENCE)
    if not audience:
        if not local_dev:
            raise ValueError(
                "OAUTH_AUDIENCE must be set for network-accessible deployments. "
                "Without it, any token from the configured issuer is accepted, including "
                "tokens intended for other services (token passthrough risk). "
                "Set OAUTH_AUDIENCE to the resource identifier for this MCP server — "
                "it must match the 'aud' claim in tokens issued by your OAuth provider "
                "and must also match what the AAS backend expects."
            )
        logger.warning(
            "OAUTH_ISSUER_URL is set but OAUTH_AUDIENCE is not. "
            "Audience validation is DISABLED — tokens intended for other resource "
            "servers may be accepted. Set OAUTH_AUDIENCE to the expected audience "
            "value (must match what the AAS backend also accepts)."
        )

    scopes_raw = os.getenv(ENV_OAUTH_REQUIRED_SCOPES)
    required_scopes: list[str] | None = None
    if scopes_raw:
        required_scopes = [
            s.strip() for s in scopes_raw.split(SCOPES_DELIMITER) if s.strip()
        ]

    explicit_jwks = os.getenv(ENV_OAUTH_JWKS_URI)
    jwks_uri = explicit_jwks or f"{issuer_url.rstrip('/')}{JWKS_WELL_KNOWN_PATH}"

    return JWTVerifier(
        jwks_uri=jwks_uri,
        issuer=issuer_url,
        audience=audience,
        required_scopes=required_scopes,
    )


def build_jwt_verifier() -> JWTVerifier | None:
    """
    Return a JWTVerifier built from environment variables, or None.

    Retained as a public function for backward-compatibility with tests.
    Uses local_dev=True (warning-only for missing audience).
    Production server construction uses build_auth_provider() which sets
    local_dev correctly based on bind address and OAUTH_SERVER_BASE_URL.
    """
    return _build_jwt_verifier_from_env(local_dev=True)


def build_auth_provider(
    host: str,
    port: int,
) -> RemoteAuthProvider | None:
    """
    Build a FastMCP RemoteAuthProvider from environment variables, or return None.

    RemoteAuthProvider wraps a JWTVerifier (for token validation) and also
    serves the /.well-known/oauth-protected-resource/mcp endpoint (RFC 9728).
    This endpoint tells MCP clients which authorization server issues valid
    tokens, allowing them to perform the PKCE browser flow automatically.

    When host is not a localhost address, OAUTH_AUDIENCE is mandatory —
    raises ValueError on startup if missing (prevents token passthrough attacks
    in network-accessible deployments without requiring a separate profile flag).

    Returns None when OAUTH_ISSUER_URL is not set (auth disabled).
    """
    # local_dev=True only when BOTH conditions are met:
    # 1. host is a localhost address (not externally bound)
    # 2. OAUTH_SERVER_BASE_URL is not set (operator has not declared a public URL)
    # If OAUTH_SERVER_BASE_URL is set, the operator declared the server is
    # reachable externally (e.g. behind a reverse proxy with localhost bind),
    # so audience enforcement must apply.
    explicit_base = os.getenv(ENV_OAUTH_SERVER_BASE_URL)
    is_localhost_bind = host in LOCALHOST_ADDRESSES
    local_dev = is_localhost_bind and not explicit_base

    jwt_verifier = _build_jwt_verifier_from_env(local_dev=local_dev)
    if jwt_verifier is None:
        return None

    issuer_url = os.getenv(ENV_OAUTH_ISSUER_URL)  # already validated non-None above

    # Derive the MCP server's public base URL for the RFC 9728 metadata endpoint.
    # explicit_base already captured above for the local_dev calculation.
    if explicit_base:
        server_base_url = explicit_base
    elif is_localhost_bind:
        # Bracket IPv6 addresses for valid URL construction
        formatted_host = f"[{host}]" if ":" in host else host
        server_base_url = f"http://{formatted_host}:{port}"
    else:
        formatted_host = f"[{host}]" if ":" in host else host
        server_base_url = f"https://{formatted_host}:{port}"

    logger.info(
        "OAuth 2.1 inbound auth enabled: issuer=%s, audience=%s, "
        "scopes=%s, jwks_uri=%s, server_base_url=%s",
        issuer_url,
        os.getenv(ENV_OAUTH_AUDIENCE) or "<not set>",
        jwt_verifier.required_scopes or "<not set>",
        jwt_verifier.jwks_uri,
        server_base_url,
    )

    return RemoteAuthProvider(
        token_verifier=jwt_verifier,
        authorization_servers=[AnyHttpUrl(issuer_url)],
        base_url=server_base_url,
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
        host: Host the server will bind to (used for TLS warning, base URL,
              and audience enforcement)
        port: Port the server will bind to (used for base URL construction)

    Returns:
        Configured FastMCP server instance

    Raises:
        ValueError: When OAuth is active, the host is non-localhost, and
                    OAUTH_AUDIENCE is not set (token passthrough prevention).
    """
    configure_logging(log_level, transport=transport)

    # Security checks for non-localhost HTTP deployments
    if os.getenv(ENV_OAUTH_ISSUER_URL) and transport in HTTP_TRANSPORTS:
        if host not in LOCALHOST_ADDRESSES:
            logger.warning(
                "OAuth is enabled but TLS termination cannot be verified. "
                "All authorization endpoints MUST be served over HTTPS in "
                "production. Ensure a TLS-terminating reverse proxy is in place."
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

    # Build HTTP client (no static auth — token forwarding via BearerTokenAuth)
    client = build_async_client(base_url=base_url)

    # Build auth provider (None when OAuth not configured).
    # Raises ValueError when host is non-localhost and OAUTH_AUDIENCE is missing.
    auth_provider = build_auth_provider(host=host, port=port)

    # Configure rate limiting (convert per-minute to per-second for token bucket)
    rate_limit = int(
        os.getenv(ENV_MCP_RATE_LIMIT_PER_MINUTE, str(DEFAULT_RATE_LIMIT_PER_MINUTE))
    )
    rate_limiter = RateLimitingMiddleware(
        max_requests_per_second=rate_limit / SECONDS_PER_MINUTE,
        burst_capacity=rate_limit,
    )

    # Generate MCP server from OpenAPI.
    # mask_error_details=True prevents internal backend error messages (stack
    # traces, AAS backend URLs, internal hostnames) from leaking to MCP clients.
    mcp = FastMCP.from_openapi(
        openapi_spec=curated,
        client=client,
        name=SERVER_NAME_FORMAT.format(component_name=component_config.component_name),
        auth=auth_provider,
        middleware=[rate_limiter],
        mask_error_details=True,
    )

    return mcp
