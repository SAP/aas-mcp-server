"""
MCP server builder for AAS components.

This module orchestrates the complete MCP server construction pipeline:
1. Load and process OpenAPI specification (with filtering and overlays)
2. Curate the spec for safe tool generation (allowlist, read-only by default)
3. Build HTTP client with authentication
4. Generate FastMCP server from curated OpenAPI spec
"""

from fastmcp import FastMCP
from .openapi_loader import load_and_process_openapi
from .http_client import build_async_client
from .tool_curation import curate_openapi_spec
from .logging import configure_logging

# Default values
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_COMPONENT_NAME = "aas-repo"

# Server name format
SERVER_NAME_FORMAT = "AAS MCP Server ({component_name})"


def build_mcp_server(
        base_url: str,
        openapi_path: str,
        enable_writes: bool,
        log_level: str = DEFAULT_LOG_LEVEL,
        component_name: str = DEFAULT_COMPONENT_NAME,
) -> FastMCP:
    """
    Build and configure an MCP server for AAS components.

    Args:
        base_url: Base URL of the AAS backend server
        openapi_path: Path to the OpenAPI specification file
        enable_writes: Whether to enable write operations (POST/PUT/PATCH/DELETE)
        log_level: Logging level (default: INFO)
        component_name: Name of the AAS component (default: aas-repo)

    Returns:
        Configured FastMCP server instance
    """
    configure_logging(log_level)

    # Load spec with optional filtering (via env var) and overlay application
    spec = load_and_process_openapi(openapi_path, component_name)

    # Curate tool surface area (rename, filter, readonly-by-default)
    curated = curate_openapi_spec(spec, enable_writes=enable_writes)

    client = build_async_client(base_url=base_url)

    # FastMCP can generate an MCP server from OpenAPI directly
    # (tools + schemas are derived from OpenAPI operations)
    mcp = FastMCP.from_openapi(
        openapi_spec=curated,
        client=client,
        name=SERVER_NAME_FORMAT.format(component_name=component_name),
    )

    return mcp