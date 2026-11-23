# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Logging configuration for AAS MCP Server.

This module provides centralized logging configuration with support
for custom log levels and per-logger configuration (e.g., reducing
httpx2 verbosity).

Trace correlation (issue #134): every record gets ``trace_id`` and
``span_id`` attributes from the active OpenTelemetry span. They are
``None`` when there is no valid span context (tracing off and no
``traceparent`` from the MCP client), so nothing changes for a plain setup.

``LOG_FORMAT`` selects the output:

* ``text`` (default): the existing human-readable line. When a trace
  context exists, ``trace_id=... span_id=...`` is appended.
* ``json``: one JSON object per line (``timestamp``, ``level``, ``logger``,
  ``message``, ``trace_id``, ``span_id`` and ``exception`` when present),
  for log collectors.

Logs still go to stderr, so the stdio transport stays protocol-clean.
"""

import json
import logging
import os
from datetime import datetime, timezone

from opentelemetry import trace

from .constants import (
    DEFAULT_LOG_FORMAT,
    ENV_LOG_FORMAT,
    LOG_FORMAT_JSON,
    LOG_FORMAT_TEXT,
)

# Environment variable names
ENV_VAR_HTTPX_LOG_LEVEL = "HTTPX_LOG_LEVEL"

# Default log level
DEFAULT_LOG_LEVEL = "INFO"

# Log format
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# Logger names
LOGGER_HTTPX = "httpx2"
LOGGER_FASTMCP = "fastmcp"
LOGGER_MCP = "mcp"

# LogRecord attributes set by TraceContextFilter
RECORD_TRACE_ID = "trace_id"
RECORD_SPAN_ID = "span_id"


class TraceContextFilter(logging.Filter):
    """Adds ``trace_id``/``span_id`` of the active OpenTelemetry span to records.

    Ids are W3C lowercase hex (32 and 16 characters), the same values as in
    ``traceparent`` and in audit events. Without a valid span context both
    are ``None``. Never drops a record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            setattr(record, RECORD_TRACE_ID, format(span_context.trace_id, "032x"))
            setattr(record, RECORD_SPAN_ID, format(span_context.span_id, "016x"))
        else:
            setattr(record, RECORD_TRACE_ID, None)
            setattr(record, RECORD_SPAN_ID, None)
        return True


class TraceTextFormatter(logging.Formatter):
    """The default text format, with the trace context appended when present."""

    def __init__(self) -> None:
        super().__init__(LOG_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        trace_id = getattr(record, RECORD_TRACE_ID, None)
        if trace_id is None:
            return line
        span_id = getattr(record, RECORD_SPAN_ID, None)
        suffix = f" trace_id={trace_id} span_id={span_id}"
        # Keep the ids on the first line when a traceback follows.
        head, sep, rest = line.partition("\n")
        return f"{head}{suffix}{sep}{rest}"


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for log collectors."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, RECORD_TRACE_ID, None),
            "span_id": getattr(record, RECORD_SPAN_ID, None),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        elif record.exc_text:
            entry["exception"] = record.exc_text
        if record.stack_info:
            entry["stack"] = self.formatStack(record.stack_info)
        return json.dumps(entry, separators=(",", ":"), default=str)


def _resolve_log_format() -> tuple[str, str | None]:
    """Return (format, invalid value or None).

    The caller warns about an invalid value only after basicConfig: logging
    before that would install a default root handler and ours would be skipped.
    """
    value = os.getenv(ENV_LOG_FORMAT, DEFAULT_LOG_FORMAT).strip().lower()
    if value in (LOG_FORMAT_TEXT, LOG_FORMAT_JSON):
        return value, None
    return DEFAULT_LOG_FORMAT, value


def _build_handler(log_format: str) -> logging.Handler:
    handler = logging.StreamHandler()  # stderr
    handler.addFilter(TraceContextFilter())
    if log_format == LOG_FORMAT_JSON:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TraceTextFormatter())
    return handler


def configure_logging(level: str = DEFAULT_LOG_LEVEL, transport: str = "stdio") -> None:
    """
    Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        transport: MCP transport type ('stdio' or 'sse')
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    log_format, invalid_log_format = _resolve_log_format()

    logging.basicConfig(
        level=log_level,
        handlers=[_build_handler(log_format)],
    )

    if invalid_log_format is not None:
        logging.warning(
            f"Invalid {ENV_LOG_FORMAT} value: '{invalid_log_format}'. "
            f"Valid values: {LOG_FORMAT_TEXT}, {LOG_FORMAT_JSON}. Using {DEFAULT_LOG_FORMAT}."
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
