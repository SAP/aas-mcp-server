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
from typing import Any

import httpx2
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer

from .constants import (
    DEFAULT_OTEL_SERVICE_NAME,
    ENV_OTEL_EXPORTER_OTLP_ENDPOINT,
    ENV_OTEL_EXPORTER_OTLP_PROTOCOL,
    ENV_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
    ENV_OTEL_EXPORTER_OTLP_TRACES_PROTOCOL,
    ENV_OTEL_SDK_DISABLED,
    ENV_OTEL_TRACES_EXPORTER,
    HTTP_ERROR_STATUS_MIN,
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


def tracing_requested() -> bool:
    """True when the standard OTEL_* variables ask for OTLP trace export."""
    if _env(ENV_OTEL_SDK_DISABLED).lower() == "true":
        return False
    exporters = {e.strip().lower() for e in _env(ENV_OTEL_TRACES_EXPORTER).split(",")}
    exporters.discard("")
    if exporters and OTEL_EXPORTER_OTLP not in exporters:
        # e.g. OTEL_TRACES_EXPORTER=none, or an exporter this server does not ship
        return False
    return bool(
        _env(ENV_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT)
        or _env(ENV_OTEL_EXPORTER_OTLP_ENDPOINT)
    )


def _otlp_protocol() -> str:
    return (
        _env(ENV_OTEL_EXPORTER_OTLP_TRACES_PROTOCOL)
        or _env(ENV_OTEL_EXPORTER_OTLP_PROTOCOL)
        or OTEL_PROTOCOL_HTTP_PROTOBUF
    ).lower()


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

    protocol = _otlp_protocol()
    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        exporter = _build_exporter(protocol)
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

    # Resource.create() merges OTEL_RESOURCE_ATTRIBUTES and OTEL_SERVICE_NAME.
    # Only fill in our default when the operator did not name the service.
    resource = Resource.create()
    service_name = str(resource.attributes.get(OTEL_SERVICE_NAME_ATTR, ""))
    if not service_name or service_name.startswith(OTEL_UNKNOWN_SERVICE_PREFIX):
        resource = resource.merge(
            Resource({OTEL_SERVICE_NAME_ATTR: DEFAULT_OTEL_SERVICE_NAME})
        )

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
    """``httpx2.AsyncClient`` that traces each request to the AAS backend.

    Opens a CLIENT span per request (parented to the active span, normally
    FastMCP's ``tools/call`` span) and injects the W3C trace context headers.
    Follows the OpenTelemetry HTTP client semantic conventions.
    """

    def __init__(self, *args: Any, tracer: Tracer | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._tracer = tracer

    def _get_tracer(self) -> Tracer:
        return self._tracer or trace.get_tracer(OTEL_INSTRUMENTATION_NAME)

    async def send(self, request: httpx2.Request, **kwargs: Any) -> httpx2.Response:
        method = request.method.upper()
        url = request.url
        attributes: dict[str, Any] = {
            "http.request.method": method,
            "url.full": _url_without_query(url),
            "url.scheme": url.scheme,
            "server.address": url.host,
        }
        if url.port:
            attributes["server.port"] = url.port

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
                span.set_attribute("error.type", type(exc).__name__)
                span.set_status(Status(StatusCode.ERROR))
                raise
            span.set_attribute("http.response.status_code", response.status_code)
            if response.status_code >= HTTP_ERROR_STATUS_MIN:
                span.set_attribute("error.type", str(response.status_code))
                span.set_status(Status(StatusCode.ERROR))
            return response
