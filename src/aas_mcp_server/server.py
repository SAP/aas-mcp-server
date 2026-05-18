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


def _build_jwt_verifier_from_env() -> JWTVerifier | None:
    """
    Build a JWTVerifier from environment variables, or return None.

    Shared implementation used by both build_jwt_verifier() and
    build_auth_provider(). Emits security warnings for missing configuration.

    Returns None when OAUTH_ISSUER_URL is not set.
    """
    issuer_url = os.getenv(ENV_OAUTH_ISSUER_URL)
    if not issuer_url:
        return None

    audience = os.getenv(ENV_OAUTH_AUDIENCE)
    if not audience:
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
    Production server construction uses build_auth_provider() which wraps
    this in a RemoteAuthProvider to also serve the RFC 9728 discovery endpoint.
    """
    return _build_jwt_verifier_from_env()


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

    Returns None when OAUTH_ISSUER_URL is not set (auth disabled).

    Security warnings:
    - Missing OAUTH_AUDIENCE: audience validation is disabled, which means
      tokens intended for other resource servers could be accepted (token
      passthrough risk per MCP Security Best Practices).
    """
    jwt_verifier = _build_jwt_verifier_from_env()
    if jwt_verifier is None:
        return None

    issuer_url = os.getenv(ENV_OAUTH_ISSUER_URL)  # already validated non-None above

    # Derive the MCP server's public base URL for the RFC 9728 metadata endpoint.
    # OAUTH_SERVER_BASE_URL can be set explicitly for reverse-proxy deployments.
    # When constructing from host:port, use https:// for non-localhost hosts
    # (localhost is used for local dev where TLS is typically not set up).
    explicit_base = os.getenv(ENV_OAUTH_SERVER_BASE_URL)
    if explicit_base:
        server_base_url = explicit_base
    elif host in LOCALHOST_ADDRESSES:
        server_base_url = f"http://{host}:{port}"
    else:
        server_base_url = f"https://{host}:{port}"

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
        host: Host the server will bind to (used for TLS warning and base URL)
        port: Port the server will bind to (used for base URL construction)

    Returns:
        Configured FastMCP server instance
    """
    configure_logging(log_level, transport=transport)

    # Security warning: OAuth over plain HTTP in non-localhost deployments
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
        spec,
        enable_writes=enable_writes,
        curation_settings=component_config.curation
    )

    # Remove schemas no longer reachable from the curated paths
    curated = prune_unused_schemas(curated)

    # Build HTTP client (no static auth — token forwarding via BearerTokenAuth)
    client = build_async_client(base_url=base_url)

    # Build auth provider (None when OAuth not configured).
    # RemoteAuthProvider = JWTVerifier + RFC 9728 protected resource metadata
    # endpoint, which tells MCP clients which authorization server to use.
    auth_provider = build_auth_provider(host=host, port=port)

    # Configure rate limiting (convert per-minute to per-second for token bucket)
    rate_limit = int(
        os.getenv(ENV_MCP_RATE_LIMIT_PER_MINUTE, str(DEFAULT_RATE_LIMIT_PER_MINUTE))
    )
    rate_limiter = RateLimitingMiddleware(
        max_requests_per_second=rate_limit / SECONDS_PER_MINUTE,
        burst_capacity=rate_limit,
    )

    # Generate MCP server from OpenAPI
    mcp = FastMCP.from_openapi(
        openapi_spec=curated,
        client=client,
        name=SERVER_NAME_FORMAT.format(
            component_name=component_config.component_name
        ),
        auth=auth_provider,
        middleware=[rate_limiter],
    )

    return mcp
