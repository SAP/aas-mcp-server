# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
MCP server builder for AAS components.

This module orchestrates the complete MCP server construction pipeline:
1. Process OpenAPI specification (derive from config + apply overlay)
2. Curate the spec for safe tool generation (allowlist, read-only by default)
3. Build HTTP client (no static auth — OAuth token is forwarded per-request)
4. Build FastMCP JWTVerifier if OAuth is configured
5. Generate FastMCP server from curated OpenAPI spec
"""

import logging
import os

from fastmcp import FastMCP
from fastmcp.server.auth import JWTVerifier
from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware

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
    ENV_MCP_RATE_LIMIT_PER_MINUTE,
)

logger = logging.getLogger(__name__)

HTTP_TRANSPORTS = frozenset({"http", "sse", "streamable-http"})
SCOPES_DELIMITER = ","


def build_jwt_verifier() -> JWTVerifier | None:
    """
    Build a FastMCP JWTVerifier from environment variables, or return None.

    Returns a JWTVerifier when OAUTH_ISSUER_URL is set, enabling inbound
    OAuth 2.1 Bearer token validation on HTTP transports. Returns None when
    OAUTH_ISSUER_URL is not set (auth disabled — current default behaviour).

    Security warnings emitted here:
    - Missing OAUTH_AUDIENCE: audience validation is disabled, which means
      tokens intended for other resource servers could be accepted (token
      passthrough risk).
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

    # Derive JWKS URI: explicit override or standard well-known path
    explicit_jwks = os.getenv(ENV_OAUTH_JWKS_URI)
    jwks_uri = explicit_jwks or f"{issuer_url.rstrip('/')}{JWKS_WELL_KNOWN_PATH}"

    logger.info(
        "OAuth 2.1 inbound auth enabled: issuer=%s, audience=%s, "
        "scopes=%s, jwks_uri=%s",
        issuer_url,
        audience or "<not set>",
        required_scopes or "<not set>",
        jwks_uri,
    )

    return JWTVerifier(
        jwks_uri=jwks_uri,
        issuer=issuer_url,
        audience=audience,
        required_scopes=required_scopes,
    )


def build_mcp_server(
        component_config: ComponentConfig,
        base_url: str,
        enable_writes: bool,
        log_level: str = DEFAULT_LOG_LEVEL,
        transport: str = "stdio",
        host: str = "127.0.0.1",
) -> FastMCP:
    """
    Build and configure an MCP server for AAS components.

    Args:
        component_config: Component configuration from config.yaml
        base_url: Base URL of the AAS backend server
        enable_writes: Whether to enable write operations (POST/PUT/PATCH/DELETE)
        log_level: Logging level (default: INFO)
        transport: MCP transport type ('stdio', 'http', 'sse', etc.)
        host: Host the server will bind to (used for TLS warning check)

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

    # Build HTTP client (no static auth — token forwarding is automatic)
    client = build_async_client(base_url=base_url)

    # Build JWT verifier (None when OAuth not configured)
    jwt_verifier = build_jwt_verifier()

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
        auth=jwt_verifier,
        middleware=[rate_limiter],
    )

    return mcp
