# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Opt-in, vendor-neutral OpenTelemetry tracing (issue #133).

FastMCP already opens a SERVER span for every ``tools/call`` through
``opentelemetry-api``. Without an SDK those calls are no-ops. This module adds
the two missing pieces:

1. :func:`configure_tracing` installs an SDK tracer provider with an OTLP
   exporter, but only when an OTLP endpoint is configured through the standard
   ``OTEL_*`` environment variables. Otherwise nothing is installed and every
   span stays a no-op.
2. :class:`TracedAsyncClient` wraps each request to the AAS backend in a CLIENT
   span (a child of the tool span) and injects W3C ``traceparent`` /
   ``tracestate`` headers, so the backend can continue the trace. The stock
   httpx instrumentation does not apply because the backend client is
   ``httpx2``.

Telemetry only goes to the OTLP endpoint; nothing is written to stdout, so the
MCP stdio protocol stream stays clean. Span attributes carry the request
method, the URL without its query string and the response status, never
headers, bodies or exception messages.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx2
from opentelemetry import metrics, propagate, trace
from opentelemetry.metrics import Meter
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer

from .constants import (
    DEFAULT_OTEL_SERVICE_NAME,
    ENV_OTEL_EXPORTER_OTLP_ENDPOINT,
    ENV_OTEL_EXPORTER_OTLP_PROTOCOL,
    ENV_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
    ENV_OTEL_EXPORTER_OTLP_TRACES_PROTOCOL,
    ENV_OTEL_SDK_DISABLED,
    ENV_OTEL_TRACES_EXPORTER,
    HTTP_CLIENT_DURATION_BUCKETS,
    HTTP_ERROR_STATUS_MIN,
    METRIC_HTTP_CLIENT_REQUEST_DURATION,
    OTEL_EXPORTER_OTLP,
    OTEL_EXTRA_HINT,
    OTEL_INSTRUMENTATION_NAME,
    OTEL_PROTOCOL_GRPC,
    OTEL_PROTOCOL_HTTP_PROTOBUF,
    OTEL_SERVICE_NAME_ATTR,
    OTEL_UNKNOWN_SERVICE_PREFIX,
)

logger = logging.getLogger(__name__)


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def otlp_export_requested(exporter_env: str, signal_endpoint_env: str) -> bool:
    """True when the standard OTEL_* variables ask for OTLP export of a signal.

    ``exporter_env`` is ``OTEL_TRACES_EXPORTER`` or ``OTEL_METRICS_EXPORTER``;
    ``signal_endpoint_env`` the matching ``OTEL_EXPORTER_OTLP_<SIGNAL>_ENDPOINT``.
    The shared ``OTEL_EXPORTER_OTLP_ENDPOINT`` turns on every signal.
    """
    if _env(ENV_OTEL_SDK_DISABLED).lower() == "true":
        return False
    exporters = {e.strip().lower() for e in _env(exporter_env).split(",")}
    exporters.discard("")
    if exporters and OTEL_EXPORTER_OTLP not in exporters:
        # e.g. OTEL_TRACES_EXPORTER=none, or an exporter this server does not ship
        return False
    return bool(_env(signal_endpoint_env) or _env(ENV_OTEL_EXPORTER_OTLP_ENDPOINT))


def tracing_requested() -> bool:
    """True when the standard OTEL_* variables ask for OTLP trace export."""
    return otlp_export_requested(
        ENV_OTEL_TRACES_EXPORTER, ENV_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
    )


def otlp_protocol(
    signal_protocol_env: str = ENV_OTEL_EXPORTER_OTLP_TRACES_PROTOCOL,
) -> str:
    """The OTLP protocol for a signal, falling back to the shared setting."""
    return (
        _env(signal_protocol_env)
        or _env(ENV_OTEL_EXPORTER_OTLP_PROTOCOL)
        or OTEL_PROTOCOL_HTTP_PROTOBUF
    ).lower()


def build_resource() -> Any:
    """SDK resource from OTEL_SERVICE_NAME / OTEL_RESOURCE_ATTRIBUTES.

    The service name defaults to ``aas-mcp-server`` when the operator did not
    name the service. Requires the SDK (the ``otel`` extra).
    """
    from opentelemetry.sdk.resources import Resource

    # Resource.create() merges OTEL_RESOURCE_ATTRIBUTES and OTEL_SERVICE_NAME.
    resource = Resource.create()
    service_name = str(resource.attributes.get(OTEL_SERVICE_NAME_ATTR, ""))
    if not service_name or service_name.startswith(OTEL_UNKNOWN_SERVICE_PREFIX):
        resource = resource.merge(
            Resource({OTEL_SERVICE_NAME_ATTR: DEFAULT_OTEL_SERVICE_NAME})
        )
    return resource


def _build_exporter(protocol: str) -> Any:
    if protocol == OTEL_PROTOCOL_GRPC:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-not-found]
            OTLPSpanExporter as GrpcSpanExporter,
        )

        return GrpcSpanExporter()
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter as HttpSpanExporter,
    )

    return HttpSpanExporter()


def configure_tracing() -> Any | None:
    """Install an OTLP-exporting tracer provider if OTEL_* config asks for one.

    Returns the installed ``TracerProvider``, or ``None`` when tracing stays off
    (not configured, disabled, or the ``otel`` extra is not installed). The
    exporter reads endpoint, headers, timeout and compression from the standard
    ``OTEL_EXPORTER_OTLP_*`` variables itself. ``OTEL_SERVICE_NAME`` and
    ``OTEL_RESOURCE_ATTRIBUTES`` are honoured; the service name defaults to
    ``aas-mcp-server``.
    """
    if not tracing_requested():
        return None

    protocol = otlp_protocol()
    try:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        exporter = _build_exporter(protocol)
        resource = build_resource()
    except ImportError:
        hint = (
            "pip install opentelemetry-exporter-otlp-proto-grpc"
            if protocol == OTEL_PROTOCOL_GRPC
            else OTEL_EXTRA_HINT
        )
        logger.warning(
            "OTLP tracing is configured but the OpenTelemetry SDK/exporter is not "
            "installed; tracing stays disabled. Install it with: %s",
            hint,
        )
        return None

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info(
        "OpenTelemetry tracing enabled (OTLP %s, service.name=%s)",
        protocol,
        resource.attributes.get(OTEL_SERVICE_NAME_ATTR),
    )
    return provider


def _url_without_query(url: httpx2.URL) -> str:
    """scheme://host[:port]/path — no userinfo, query or fragment."""
    port = f":{url.port}" if url.port else ""
    return f"{url.scheme}://{url.host}{port}{url.path}"


class TracedAsyncClient(httpx2.AsyncClient):
    """``httpx2.AsyncClient`` that instruments each request to the AAS backend.

    Opens a CLIENT span per request (parented to the active span, normally
    FastMCP's ``tools/call`` span), injects the W3C trace context headers and
    records the ``http.client.request.duration`` histogram. Follows the
    OpenTelemetry HTTP client semantic conventions. Without an SDK provider
    the span and the measurement are no-ops.
    """

    def __init__(
        self,
        *args: Any,
        tracer: Tracer | None = None,
        meter: Meter | None = None,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self._tracer = tracer
        # Created once; through the global meter, the instrument binds to a
        # provider installed later (opentelemetry-api proxy meter).
        self._duration = (
            meter or metrics.get_meter(OTEL_INSTRUMENTATION_NAME)
        ).create_histogram(
            METRIC_HTTP_CLIENT_REQUEST_DURATION,
            unit="s",
            description="Duration of HTTP client requests to the AAS backend.",
            explicit_bucket_boundaries_advisory=HTTP_CLIENT_DURATION_BUCKETS,
        )

    def _get_tracer(self) -> Tracer:
        return self._tracer or trace.get_tracer(OTEL_INSTRUMENTATION_NAME)

    async def send(self, request: httpx2.Request, **kwargs: Any) -> httpx2.Response:
        method = request.method.upper()
        url = request.url
        # Low-cardinality attributes shared by the span and the metric. The
        # metric never carries the URL: paths contain AAS identifiers.
        common: dict[str, Any] = {
            "http.request.method": method,
            "server.address": url.host,
        }
        if url.port:
            common["server.port"] = url.port
        attributes: dict[str, Any] = {
            **common,
            "url.full": _url_without_query(url),
            "url.scheme": url.scheme,
        }

        started = time.perf_counter()
        with self._get_tracer().start_as_current_span(
            method,
            kind=SpanKind.CLIENT,
            attributes=attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            propagate.inject(request.headers)
            try:
                response = await super().send(request, **kwargs)
            except Exception as exc:
                # Type only: messages can contain backend URLs or data.
                error_type = type(exc).__name__
                span.set_attribute("error.type", error_type)
                span.set_status(Status(StatusCode.ERROR))
                self._duration.record(
                    time.perf_counter() - started,
                    {**common, "error.type": error_type},
                )
                raise
            span.set_attribute("http.response.status_code", response.status_code)
            metric_attributes = {
                **common,
                "http.response.status_code": response.status_code,
            }
            if response.status_code >= HTTP_ERROR_STATUS_MIN:
                span.set_attribute("error.type", str(response.status_code))
                span.set_status(Status(StatusCode.ERROR))
                metric_attributes["error.type"] = str(response.status_code)
            self._duration.record(time.perf_counter() - started, metric_attributes)
            return response
