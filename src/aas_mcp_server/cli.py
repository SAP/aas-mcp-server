# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Command-line interface for AAS MCP Server.

This module provides the main CLI entry point for running the AAS MCP server.
All configuration is loaded from a config.yaml file (required).

Config File Location:
- Default: /app/config/config.yaml
- Override: --config CLI flag or CONFIG_PATH environment variable
"""

import argparse
import os
import sys
import logging

from .config import load_config, ConfigError
from .server import build_mcp_server
from .logging import configure_logging


# Environment variables
ENV_VAR_MCP_TRANSPORT = "MCP_TRANSPORT"
ENV_VAR_AAS_MCP_ENABLE_WRITES = "AAS_MCP_ENABLE_WRITES"
ENV_VAR_LOG_LEVEL = "LOG_LEVEL"
ENV_VAR_AAS_BASE_URL = "AAS_BASE_URL"

# Default values
DEFAULT_TRANSPORT = "stdio"
DEFAULT_LOG_LEVEL = "INFO"
ENABLE_WRITES_TRUE_VALUE = "1"

# CLI program info
CLI_PROGRAM_NAME = "aas-mcp-server"
CLI_DESCRIPTION = """AAS MCP Server - OpenAPI to MCP Bridge for Asset Administration Shell APIs

Requires a configuration file (config.yaml) that defines component specifications.
Default location: /app/config/config.yaml
Override with: --config flag or CONFIG_PATH environment variable
"""


def main() -> None:
    """
    Main entry point for the AAS MCP Server CLI.

    Loads configuration from config.yaml and starts the MCP server for the specified component.
    """
    parser = argparse.ArgumentParser(
        prog=CLI_PROGRAM_NAME,
        description=CLI_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # Required arguments
    parser.add_argument(
        "--component",
        required=True,
        help="AAS component to serve (must be defined in config.yaml). "
             "Examples: aas-repo, submodel-repo, aas-registry, submodel-registry"
    )

    parser.add_argument(
        "--base-url",
        help="Base URL for the component API (overrides config default). "
             "Can also be set via AAS_BASE_URL environment variable."
    )

    # Optional arguments
    parser.add_argument(
        "--config",
        help="Path to configuration file (default: /app/config/config.yaml). "
             "Can also be set via CONFIG_PATH environment variable."
    )

    parser.add_argument(
        "--transport",
        default=os.getenv(ENV_VAR_MCP_TRANSPORT, DEFAULT_TRANSPORT),
        choices=["stdio", "http", "sse", "streamable-http"],
        help="MCP transport protocol (default: stdio)"
    )

    parser.add_argument(
        "--host",
        default=os.getenv("MCP_HOST", "127.0.0.1"),
        help="Host to bind HTTP/SSE server to (default: 127.0.0.1)"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_PORT", "8000")),
        help="Port to bind HTTP/SSE server to (default: 8000)"
    )

    parser.add_argument(
        "--enable-writes",
        action="store_true",
        default=os.getenv(ENV_VAR_AAS_MCP_ENABLE_WRITES) == ENABLE_WRITES_TRUE_VALUE,
        help="Enable write operations (POST/PUT/PATCH/DELETE). "
             "Can also be set via AAS_MCP_ENABLE_WRITES=1"
    )

    parser.add_argument(
        "--log-level",
        default=os.getenv(ENV_VAR_LOG_LEVEL, DEFAULT_LOG_LEVEL),
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)"
    )

    args = parser.parse_args()

    # Setup logging
    configure_logging(args.log_level, args.transport)
    logger = logging.getLogger(__name__)

    # Load configuration
    try:
        config = load_config(args.config)
        logger.info(f"Loaded configuration from: {config.config_path}")
        logger.debug(f"Available components: {list(config.components.keys())}")
    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    # Get component configuration
    try:
        component_config = config.get_component(args.component)
        logger.info(f"Using component configuration: {component_config}")
    except ConfigError as e:
        logger.error(str(e))
        sys.exit(1)

    # Determine base URL (CLI arg > env var > required error)
    base_url = args.base_url or os.getenv(ENV_VAR_AAS_BASE_URL)
    if not base_url:
        logger.error(
            "Base URL is required. Provide via --base-url flag or "
            "AAS_BASE_URL environment variable."
        )
        sys.exit(1)

    logger.info(f"Component: {args.component}, Base URL: {base_url}")

    # Build MCP server
    try:
        mcp = build_mcp_server(
            component_config=component_config,
            base_url=base_url,
            enable_writes=args.enable_writes,
            log_level=args.log_level,
            transport=args.transport,
            host=args.host,
        )
    except Exception as e:
        logger.error(f"Failed to build MCP server: {e}", exc_info=True)
        sys.exit(1)

    # Prepare transport kwargs for HTTP/SSE transports
    transport_kwargs = {}
    if args.transport in ["http", "sse", "streamable-http"]:
        transport_kwargs["host"] = args.host
        transport_kwargs["port"] = args.port

    # Run the server
    logger.info(f"Starting MCP server with transport: {args.transport}")
    mcp.run(transport=args.transport, show_banner=False, **transport_kwargs)


if __name__ == "__main__":
    main()
