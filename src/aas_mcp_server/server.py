# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
MCP server builder for AAS components.

This module orchestrates the complete MCP server construction pipeline:
1. Process OpenAPI specification (derive from config + apply overlay)
2. Curate the spec for safe tool generation (allowlist, read-only by default)
3. Build HTTP client with authentication
4. Generate FastMCP server from curated OpenAPI spec
"""

from fastmcp import FastMCP

from .config import ComponentConfig
from .spec_processor import process_component_spec
from .http_client import build_async_client
from .tool_curation import curate_openapi_spec
from .logging import configure_logging
from .constants import DEFAULT_LOG_LEVEL, SERVER_NAME_FORMAT


def build_mcp_server(
        component_config: ComponentConfig,
        base_url: str,
        enable_writes: bool,
        log_level: str = DEFAULT_LOG_LEVEL,
        transport: str = "stdio",
) -> FastMCP:
    """
    Build and configure an MCP server for AAS components.

    Args:
        component_config: Component configuration from config.yaml
        base_url: Base URL of the AAS backend server
        enable_writes: Whether to enable write operations (POST/PUT/PATCH/DELETE)
        log_level: Logging level (default: INFO)
        transport: MCP transport type ('stdio', 'http', 'sse', etc.)

    Returns:
        Configured FastMCP server instance
    """
    configure_logging(log_level, transport=transport)

    # Process spec according to config (derive + apply overlay)
    spec = process_component_spec(component_config)

    # Curate tool surface area (rename, filter, readonly-by-default)
    curated = curate_openapi_spec(
        spec,
        enable_writes=enable_writes,
        curation_settings=component_config.curation
    )

    # Build HTTP client
    client = build_async_client(base_url=base_url)

    # Generate MCP server from OpenAPI
    mcp = FastMCP.from_openapi(
        openapi_spec=curated,
        client=client,
        name=SERVER_NAME_FORMAT.format(component_name=component_config.component_name),
    )

    return mcp
