# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Opt-in, vendor-neutral OpenTelemetry metrics (issue #134).

:func:`configure_metrics` installs an SDK meter provider with a periodic OTLP
exporter, but only when the standard ``OTEL_*`` variables ask for it (the same
rules as tracing, with ``OTEL_METRICS_EXPORTER`` and
``OTEL_EXPORTER_OTLP_METRICS_ENDPOINT``). Otherwise nothing is installed and
every instrument stays a no-op.

Instruments:

* ``mcp.server.operation.duration`` (histogram, s): every MCP request seen by
  :class:`MetricsMiddleware`, with ``mcp.method.name``, ``gen_ai.tool.name``
  for tool calls and ``error.type`` on failure. Its count is the request count.
* ``http.client.request.duration`` (histogram, s): every request to the AAS
  backend, recorded by :class:`~aas_mcp_server.tracing.TracedAsyncClient`.
* ``aas_mcp.backend_token.cache.lookups`` (counter): backend token cache hits
  and misses, recorded in ``backend_auth``.
* ``aas_mcp.rate_limit.rejections`` (counter): requests rejected by the rate
  limiter, recorded by :class:`MetricsMiddleware`.

Attributes are low-cardinality only: no URLs, identifiers, subjects, client
ids or messages. Metrics only go to the OTLP endpoint, never to stdout, so the
stdio transport stays protocol-clean.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx2
from fastmcp.exceptions import NotFoundError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.middleware.rate_limiting import RateLimitError
from opentelemetry import metrics
from opentelemetry.metrics import Meter

from .audit import _exception_chain
from .constants import (
    ENV_OTEL_EXPORTER_OTLP_METRICS_ENDPOINT,
    ENV_OTEL_EXPORTER_OTLP_METRICS_PROTOCOL,
    ENV_OTEL_METRICS_EXPORTER,
    MCP_OPERATION_DURATION_BUCKETS,
    METRIC_MCP_SERVER_OPERATION_DURATION,
    METRIC_RATE_LIMIT_REJECTIONS,
    OTEL_EXTRA_HINT,
    OTEL_INSTRUMENTATION_NAME,
    OTEL_PROTOCOL_GRPC,
    OTEL_SERVICE_NAME_ATTR,
)
from .tracing import build_resource, otlp_export_requested, otlp_protocol

logger = logging.getLogger(__name__)

MCP_METHOD_TOOLS_CALL = "tools/call"


def metrics_requested() -> bool:
    """True when the standard OTEL_* variables ask for OTLP metric export."""
    return otlp_export_requested(
        ENV_OTEL_METRICS_EXPORTER, ENV_OTEL_EXPORTER_OTLP_METRICS_ENDPOINT
    )


def _build_metric_exporter(protocol: str) -> Any:
    if protocol == OTEL_PROTOCOL_GRPC:
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (  # type: ignore[import-not-found]
            OTLPMetricExporter as GrpcMetricExporter,
        )

        return GrpcMetricExporter()
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter as HttpMetricExporter,
    )

    return HttpMetricExporter()


def configure_metrics() -> Any | None:
    """Install an OTLP-exporting meter provider if OTEL_* config asks for one.

    Returns the installed ``MeterProvider``, or ``None`` when metrics stay off
    (not configured, disabled, or the ``otel`` extra is not installed). The
    exporter reads endpoint, headers, timeout and compression from the standard
    ``OTEL_EXPORTER_OTLP_*`` variables, and the reader reads the export
    interval from ``OTEL_METRIC_EXPORT_INTERVAL``.
    """
    if not metrics_requested():
        return None

    protocol = otlp_protocol(ENV_OTEL_EXPORTER_OTLP_METRICS_PROTOCOL)
    try:
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        exporter = _build_metric_exporter(protocol)
        resource = build_resource()
    except ImportError:
        hint = (
            "pip install opentelemetry-exporter-otlp-proto-grpc"
            if protocol == OTEL_PROTOCOL_GRPC
            else OTEL_EXTRA_HINT
        )
        logger.warning(
            "OTLP metrics are configured but the OpenTelemetry SDK/exporter is not "
            "installed; metrics stay disabled. Install it with: %s",
            hint,
        )
        return None

    provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(exporter)],
    )
    metrics.set_meter_provider(provider)
    logger.info(
        "OpenTelemetry metrics enabled (OTLP %s, service.name=%s)",
        protocol,
        resource.attributes.get(OTEL_SERVICE_NAME_ATTR),
    )
    return provider


def _error_type(exc: BaseException) -> str:
    """Low-cardinality ``error.type`` for a failed MCP request.

    Denials keep their class name, backend HTTP errors use the status code (as
    on the backend span), anything else the root cause's class name (FastMCP
    wraps tool errors in ``ToolError``). Never the message.
    """
    chain = _exception_chain(exc)
    for item in chain:
        if isinstance(item, (RateLimitError, NotFoundError)):
            return type(item).__name__
        if isinstance(item, httpx2.HTTPStatusError):
            return str(item.response.status_code)
    return type(chain[-1]).__name__


def _is_rate_limited(exc: BaseException) -> bool:
    return any(isinstance(item, RateLimitError) for item in _exception_chain(exc))


class MetricsMiddleware(Middleware):
    """Records ``mcp.server.operation.duration`` and rate-limit rejections.

    Place it first in the middleware list so that requests the rate limiter
    rejects are measured too.
    """

    def __init__(self, meter: Meter | None = None) -> None:
        meter = meter or metrics.get_meter(OTEL_INSTRUMENTATION_NAME)
        self._duration = meter.create_histogram(
            METRIC_MCP_SERVER_OPERATION_DURATION,
            unit="s",
            description="Duration of MCP requests as seen by the server.",
            explicit_bucket_boundaries_advisory=MCP_OPERATION_DURATION_BUCKETS,
        )
        self._rate_limited = meter.create_counter(
            METRIC_RATE_LIMIT_REJECTIONS,
            unit="{request}",
            description="MCP requests rejected by the rate limiter.",
        )

    async def on_request(
        self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]
    ) -> Any:
        method = context.method or "unknown"
        attributes: dict[str, Any] = {"mcp.method.name": method}
        if method == MCP_METHOD_TOOLS_CALL:
            tool_name = getattr(context.message, "name", None)
            if tool_name:
                attributes["gen_ai.tool.name"] = tool_name

        started = time.perf_counter()
        try:
            result = await call_next(context)
        except Exception as exc:
            attributes["error.type"] = _error_type(exc)
            self._duration.record(time.perf_counter() - started, attributes)
            if _is_rate_limited(exc):
                self._rate_limited.add(1, {"mcp.method.name": method})
            raise
        self._duration.record(time.perf_counter() - started, attributes)
        return result
