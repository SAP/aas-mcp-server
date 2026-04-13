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


def configure_logging(level: str = DEFAULT_LOG_LEVEL) -> None:
    """
    Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=LOG_FORMAT,
    )
    # Reduce noisy logs if desired
    httpx_log_level = os.getenv(ENV_VAR_HTTPX_LOG_LEVEL)
    if httpx_log_level:
        logging.getLogger(LOGGER_HTTPX).setLevel(httpx_log_level)
