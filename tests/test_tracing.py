# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for opt-in OpenTelemetry tracing (issue #133).

Spans are captured with the SDK's in-memory exporter; the AAS backend is an
httpx2 MockTransport that records the headers it receives.
"""

import builtins
import sys
import types
from unittest.mock import MagicMock, patch

import httpx2
import pytest
from fastmcp import Client, FastMCP
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

import aas_mcp_server.tracing as tracing
from aas_mcp_server.http_client import build_async_client
from aas_mcp_server.server import build_mcp_server
from aas_mcp_server.constants import DEFAULT_OTEL_SERVICE_NAME
from aas_mcp_server.tracing import (
    TracedAsyncClient,
    configure_tracing,
    tracing_requested,
)

BACKEND = "http://aas-backend.test:8081"

OTEL_VARS = [
    "OTEL_SDK_DISABLED",
    "OTEL_TRACES_EXPORTER",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
    "OTEL_SERVICE_NAME",
    "OTEL_RESOURCE_ATTRIBUTES",
]

SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "test", "version": "1"},
    "paths": {
        "/shells": {
            "get": {
                "operationId": "GetAllShells",
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}


@pytest.fixture(autouse=True)
def clean_otel_env(monkeypatch):
    for name in OTEL_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield provider, exporter
    provider.shutdown()


class RecordingBackend:
    def __init__(self, status=200, raise_exc=None):
        self.status = status
        self.raise_exc = raise_exc
        self.headers: list[httpx2.Headers] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.headers.append(request.headers)
        if self.raise_exc:
            raise self.raise_exc
        return httpx2.Response(self.status, json={"result": []})


def _client(backend, tracer):
    return TracedAsyncClient(
        base_url=BACKEND, transport=httpx2.MockTransport(backend), tracer=tracer
    )


# ---------------------------------------------------------------------------
# Gating: tracing only turns on through standard OTEL_* configuration
# ---------------------------------------------------------------------------


class TestTracingRequested:
    def test_off_without_endpoint(self):
        assert tracing_requested() is False
        assert configure_tracing() is None

    @pytest.mark.parametrize(
        "var", ["OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"]
    )
    def test_on_with_endpoint(self, monkeypatch, var):
        monkeypatch.setenv(var, "http://collector:4318")
        assert tracing_requested() is True

    def test_sdk_disabled_wins(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
        assert tracing_requested() is False

    @pytest.mark.parametrize("value", ["none", "console", "zipkin"])
    def test_non_otlp_exporter_is_off(self, monkeypatch, value):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        monkeypatch.setenv("OTEL_TRACES_EXPORTER", value)
        assert tracing_requested() is False

    def test_otlp_exporter_listed(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        monkeypatch.setenv("OTEL_TRACES_EXPORTER", "otlp")
        assert tracing_requested() is True


class TestConfigureTracing:
    def _configure(self, monkeypatch):
        installed = []
        monkeypatch.setattr(tracing.trace, "set_tracer_provider", installed.append)
        provider = configure_tracing()
        return provider, installed

    def test_installs_provider_with_default_service_name(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        provider, installed = self._configure(monkeypatch)
        try:
            assert installed == [provider]
            assert (
                provider.resource.attributes["service.name"]
                == DEFAULT_OTEL_SERVICE_NAME
            )
        finally:
            provider.shutdown()

    def test_operator_service_name_is_kept(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        monkeypatch.setenv("OTEL_SERVICE_NAME", "aas-mcp-plant-7")
        monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=qa")
        provider, _ = self._configure(monkeypatch)
        try:
            attrs = provider.resource.attributes
            assert attrs["service.name"] == "aas-mcp-plant-7"
            assert attrs["deployment.environment"] == "qa"
        finally:
            provider.shutdown()

    def test_missing_extra_warns_and_stays_off(self, monkeypatch, caplog):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("opentelemetry.sdk") or name.startswith(
                "opentelemetry.exporter"
            ):
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        provider, installed = self._configure(monkeypatch)
        assert provider is None
        assert installed == []
        assert "aas-mcp-server[otel]" in caplog.text

    def test_grpc_without_grpc_exporter_stays_off(self, monkeypatch, caplog):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if "otlp.proto.grpc" in name:
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        provider, _ = self._configure(monkeypatch)
        assert provider is None
        assert "opentelemetry-exporter-otlp-proto-grpc" in caplog.text

    def test_grpc_protocol_uses_grpc_exporter(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", "grpc")
        grpc_module = types.ModuleType("grpc_trace_exporter")
        grpc_module.OTLPSpanExporter = MagicMock(name="GrpcSpanExporter")
        monkeypatch.setitem(
            sys.modules,
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
            grpc_module,
        )
        provider, _ = self._configure(monkeypatch)
        try:
            grpc_module.OTLPSpanExporter.assert_called_once_with()
        finally:
            provider.shutdown()

    def test_never_writes_to_stdout(self, monkeypatch, capsys):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        provider, _ = self._configure(monkeypatch)
        provider.shutdown()
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# Backend CLIENT spans and trace-context propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTracedAsyncClient:
    async def test_client_span_and_traceparent(self, spans):
        provider, exporter = spans
        tracer = provider.get_tracer("test")
        backend = RecordingBackend()

        with tracer.start_as_current_span("tools/call GetAllShells") as parent:
            async with _client(backend, tracer) as client:
                await client.get("/shells", params={"cursor": "secret-cursor"})

        client_span = next(s for s in exporter.get_finished_spans() if s.name == "GET")
        assert client_span.kind == SpanKind.CLIENT
        assert client_span.parent.span_id == parent.get_span_context().span_id
        attrs = client_span.attributes
        assert attrs["http.request.method"] == "GET"
        assert attrs["url.full"] == f"{BACKEND}/shells"
        assert attrs["server.address"] == "aas-backend.test"
        assert attrs["server.port"] == 8081
        assert attrs["http.response.status_code"] == 200
        assert "secret-cursor" not in str(dict(attrs))

        traceparent = backend.headers[0]["traceparent"]
        trace_id = format(client_span.context.trace_id, "032x")
        span_id = format(client_span.context.span_id, "016x")
        version, sent_trace_id, sent_span_id, flags = traceparent.split("-")
        assert (version, sent_trace_id, sent_span_id) == ("00", trace_id, span_id)
        assert int(flags, 16) & 0x01  # sampled

    async def test_error_status_marks_span(self, spans):
        provider, exporter = spans
        async with _client(RecordingBackend(status=503), provider.get_tracer("t")) as c:
            await c.get("/shells")

        [span] = exporter.get_finished_spans()
        assert span.status.status_code == StatusCode.ERROR
        assert span.attributes["error.type"] == "503"

    async def test_transport_exception_records_type_only(self, spans):
        provider, exporter = spans
        backend = RecordingBackend(raise_exc=httpx2.ConnectError("10.1.2.3 refused"))
        async with _client(backend, provider.get_tracer("t")) as c:
            with pytest.raises(httpx2.ConnectError):
                await c.get("/shells")

        [span] = exporter.get_finished_spans()
        assert span.status.status_code == StatusCode.ERROR
        assert span.attributes["error.type"] == "ConnectError"
        assert not span.events  # no exception event carrying the message
        assert "10.1.2.3" not in str(dict(span.attributes))

    async def test_fastmcp_tool_span_parents_backend_span(self, spans, monkeypatch):
        """End to end: FastMCP's tools/call span → our CLIENT span → backend."""
        provider, exporter = spans
        # FastMCP looks up the global provider; swap it in for this test only.
        monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider)
        backend = RecordingBackend()
        client = TracedAsyncClient(
            base_url=BACKEND, transport=httpx2.MockTransport(backend)
        )
        server = FastMCP.from_openapi(openapi_spec=SPEC, client=client)

        async with Client(server) as c:
            await c.call_tool("GetAllShells", {})

        finished = exporter.get_finished_spans()
        tool_span = next(s for s in finished if s.name == "tools/call GetAllShells")
        backend_span = next(s for s in finished if s.name == "GET")
        assert backend_span.parent.span_id == tool_span.context.span_id
        assert backend_span.context.trace_id == tool_span.context.trace_id
        assert (
            format(tool_span.context.trace_id, "032x")
            in backend.headers[0]["traceparent"]
        )


# ---------------------------------------------------------------------------
# Wiring in build_async_client / build_mcp_server
# ---------------------------------------------------------------------------


class TestWiring:
    def test_plain_client_by_default(self):
        client = build_async_client(base_url=BACKEND)
        assert type(client) is httpx2.AsyncClient

    def test_traced_client_on_request(self):
        client = build_async_client(base_url=BACKEND, traced=True)
        assert isinstance(client, TracedAsyncClient)

    def _build(self, configured_provider):
        component = MagicMock()
        component.component_name = "aas-repo"
        component.curation = None
        with (
            patch(
                "aas_mcp_server.server.process_component_spec",
                return_value={"paths": {}},
            ),
            patch(
                "aas_mcp_server.server.flatten_spec_schemas", side_effect=lambda s: s
            ),
            patch(
                "aas_mcp_server.server.curate_openapi_spec", return_value={"paths": {}}
            ),
            patch(
                "aas_mcp_server.server.prune_unused_schemas", side_effect=lambda s: s
            ),
            patch("aas_mcp_server.server.build_async_client") as build_client,
            patch(
                "aas_mcp_server.server.configure_tracing",
                return_value=configured_provider,
            ),
            patch("aas_mcp_server.server.FastMCP"),
        ):
            build_mcp_server(component, base_url=BACKEND, enable_writes=False)
        return build_client.call_args.kwargs

    def test_server_uses_plain_client_when_tracing_off(self):
        assert "traced" not in self._build(None)

    def test_server_uses_traced_client_when_tracing_on(self):
        assert self._build(object())["traced"] is True
