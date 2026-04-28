# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Logging configuration for AAS MCP Server.

This module provides centralized logging configuration with support
for custom log levels and per-logger configuration (e.g., reducing
httpx verbosity).
"""

import logging
import os

# Environment variable names
ENV_VAR_HTTPX_LOG_LEVEL = "HTTPX_LOG_LEVEL"

# Default log level
DEFAULT_LOG_LEVEL = "INFO"

# Log format
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# Logger names
LOGGER_HTTPX = "httpx"
LOGGER_FASTMCP = "fastmcp"
LOGGER_MCP = "mcp"


def configure_logging(level: str = DEFAULT_LOG_LEVEL, transport: str = "stdio") -> None:
    """
    Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        transport: MCP transport type ('stdio' or 'sse')
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format=LOG_FORMAT,
    )

    # For stdio transport, suppress FastMCP logs completely to avoid
    # polluting stderr, which would break MCP protocol communication.
    # Only show CRITICAL errors that indicate actual failures.
    if transport == "stdio":
        logging.getLogger(LOGGER_FASTMCP).setLevel(logging.CRITICAL)
        logging.getLogger(LOGGER_MCP).setLevel(logging.CRITICAL)
    else:
        # For other transports (SSE), match the configured log level
        logging.getLogger(LOGGER_FASTMCP).setLevel(log_level)
        logging.getLogger(LOGGER_MCP).setLevel(log_level)

    # Reduce noisy logs if desired
    httpx_log_level_str = os.getenv(ENV_VAR_HTTPX_LOG_LEVEL)
    if httpx_log_level_str:
        httpx_log_level = getattr(logging, httpx_log_level_str.upper(), None)
        if httpx_log_level is not None:
            logging.getLogger(LOGGER_HTTPX).setLevel(httpx_log_level)
        else:
            logging.warning(
                f"Invalid {ENV_VAR_HTTPX_LOG_LEVEL} value: '{httpx_log_level_str}'. "
                f"Valid values: DEBUG, INFO, WARNING, ERROR, CRITICAL"
            )
