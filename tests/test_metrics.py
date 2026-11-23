# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for opt-in OpenTelemetry metrics (issue #134).

Measurements are read with the SDK's InMemoryMetricReader. Tool calls run end
to end through a real FastMCP server generated from a small OpenAPI spec, with
the AAS backend replaced by an httpx2 MockTransport.
"""

import asyncio
import builtins
import sys
import types
from unittest.mock import MagicMock, patch

import httpx2
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from fastmcp.server.middleware.rate_limiting import (
    RateLimitError,
    RateLimitingMiddleware,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

import aas_mcp_server.metrics as metrics_module
from aas_mcp_server.backend_auth import _KeyedTokenCache  # type: ignore[attr-defined]
from aas_mcp_server.constants import (
    DEFAULT_OTEL_SERVICE_NAME,
    HTTP_CLIENT_DURATION_BUCKETS,
    MCP_OPERATION_DURATION_BUCKETS,
)
from aas_mcp_server.metrics import (
    MetricsMiddleware,
    _error_type,
    configure_metrics,
    metrics_requested,
)
from aas_mcp_server.server import build_mcp_server
from aas_mcp_server.tracing import TracedAsyncClient

BACKEND = "http://aas-backend.test:8081"
AAS_ID = "aHR0cHM6Ly9leGFtcGxlLmNvbS9hYXMvMQ"

OTEL_VARS = [
    "OTEL_SDK_DISABLED",
    "OTEL_TRACES_EXPORTER",
    "OTEL_METRICS_EXPORTER",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL",
    "OTEL_SERVICE_NAME",
    "OTEL_RESOURCE_ATTRIBUTES",
]

SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "test", "version": "1"},
    "paths": {
        "/shells/{aasIdentifier}": {
            "get": {
                "operationId": "GetShell",
                "parameters": [
                    {
                        "name": "aasIdentifier",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
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
def reader():
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    reader.meter = provider.get_meter("test")
    yield reader
    provider.shutdown()


def _points(reader: InMemoryMetricReader, name: str) -> list:
    data = reader.get_metrics_data()
    if data is None:
        return []
    return [
        point
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
        if metric.name == name
        for point in metric.data.data_points
    ]


def _server(reader, status=200, rate_limiter=None):
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"id": "x"})

    middleware = [MetricsMiddleware(meter=reader.meter)]
    if rate_limiter is not None:
        middleware.append(rate_limiter)
    return FastMCP.from_openapi(
        openapi_spec=SPEC,
        client=TracedAsyncClient(
            base_url=BACKEND,
            transport=httpx2.MockTransport(handler),
            meter=reader.meter,
        ),
        middleware=middleware,
        mask_error_details=True,
    )


# ---------------------------------------------------------------------------
# Gating: metrics only turn on through standard OTEL_* configuration
# ---------------------------------------------------------------------------


class TestMetricsRequested:
    def test_off_without_endpoint(self):
        assert not metrics_requested()
        assert configure_metrics() is None

    @pytest.mark.parametrize(
        "var", ["OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"]
    )
    def test_on_with_endpoint(self, monkeypatch, var):
        monkeypatch.setenv(var, "http://collector:4318")
        assert metrics_requested()

    def test_traces_only_endpoint_does_not_enable_metrics(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://c:4318")
        assert not metrics_requested()

    def test_sdk_disabled_wins(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
        assert not metrics_requested()

    @pytest.mark.parametrize("value", ["none", "console", "prometheus"])
    def test_non_otlp_exporter_is_off(self, monkeypatch, value):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        monkeypatch.setenv("OTEL_METRICS_EXPORTER", value)
        assert not metrics_requested()

    def test_metrics_exporter_none_keeps_tracing(self, monkeypatch):
        """Turning metrics off must not turn tracing off (separate variables)."""
        from aas_mcp_server.tracing import tracing_requested

        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        monkeypatch.setenv("OTEL_METRICS_EXPORTER", "none")
        assert not metrics_requested()
        assert tracing_requested()


class TestConfigureMetrics:
    def _configure(self, monkeypatch):
        installed = []
        monkeypatch.setattr(
            metrics_module.metrics, "set_meter_provider", installed.append
        )
        return configure_metrics(), installed

    def test_installs_provider_with_default_service_name(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        provider, installed = self._configure(monkeypatch)
        try:
            assert installed == [provider]
            assert isinstance(provider, MeterProvider)
            resource = provider._sdk_config.resource
            assert resource.attributes["service.name"] == DEFAULT_OTEL_SERVICE_NAME
        finally:
            provider.shutdown()

    def test_operator_service_name_is_kept(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "http://c:4318")
        monkeypatch.setenv("OTEL_SERVICE_NAME", "aas-mcp-plant-7")
        provider, _ = self._configure(monkeypatch)
        try:
            resource = provider._sdk_config.resource
            assert resource.attributes["service.name"] == "aas-mcp-plant-7"
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

    def test_grpc_protocol_uses_grpc_exporter(self, monkeypatch):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_METRICS_PROTOCOL", "grpc")
        grpc_module = types.ModuleType("grpc_metric_exporter")
        exporter = MagicMock(name="GrpcMetricExporter")
        exporter.return_value._preferred_temporality = {}
        exporter.return_value._preferred_aggregation = {}
        grpc_module.OTLPMetricExporter = exporter
        monkeypatch.setitem(
            sys.modules,
            "opentelemetry.exporter.otlp.proto.grpc.metric_exporter",
            grpc_module,
        )
        provider, _ = self._configure(monkeypatch)
        try:
            exporter.assert_called_once_with()
        finally:
            provider.shutdown()

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

    def test_never_writes_to_stdout(self, monkeypatch, capsys):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
        provider, _ = self._configure(monkeypatch)
        provider.shutdown()
        assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# Tool calls end to end: MCP operation and backend request durations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestToolCallMetrics:
    async def test_successful_call(self, reader):
        async with Client(_server(reader)) as client:
            await client.call_tool("GetShell", {"aasIdentifier": AAS_ID})

        [tool_point] = [
            p
            for p in _points(reader, "mcp.server.operation.duration")
            if p.attributes["mcp.method.name"] == "tools/call"
        ]
        assert dict(tool_point.attributes) == {
            "mcp.method.name": "tools/call",
            "gen_ai.tool.name": "GetShell",
        }
        assert tool_point.count == 1
        assert tuple(tool_point.explicit_bounds) == MCP_OPERATION_DURATION_BUCKETS

        [http_point] = _points(reader, "http.client.request.duration")
        assert dict(http_point.attributes) == {
            "http.request.method": "GET",
            "server.address": "aas-backend.test",
            "server.port": 8081,
            "http.response.status_code": 200,
        }
        assert http_point.count == 1
        assert tuple(http_point.explicit_bounds) == HTTP_CLIENT_DURATION_BUCKETS

    async def test_other_mcp_methods_are_measured(self, reader):
        async with Client(_server(reader)) as client:
            await client.list_tools()

        methods = {
            p.attributes["mcp.method.name"]
            for p in _points(reader, "mcp.server.operation.duration")
        }
        assert "tools/list" in methods

    async def test_backend_error(self, reader):
        async with Client(_server(reader, status=500)) as client:
            with pytest.raises(ToolError):
                await client.call_tool("GetShell", {"aasIdentifier": AAS_ID})

        [tool_point] = [
            p
            for p in _points(reader, "mcp.server.operation.duration")
            if p.attributes["mcp.method.name"] == "tools/call"
        ]
        assert tool_point.attributes["error.type"] == "500"
        [http_point] = _points(reader, "http.client.request.duration")
        assert http_point.attributes["http.response.status_code"] == 500
        assert http_point.attributes["error.type"] == "500"

    async def test_backend_unreachable(self, reader):
        def handler(request):
            raise httpx2.ConnectError("refused")

        client = TracedAsyncClient(
            base_url=BACKEND,
            transport=httpx2.MockTransport(handler),
            meter=reader.meter,
        )
        with pytest.raises(httpx2.ConnectError):
            await client.get("/shells")

        [http_point] = _points(reader, "http.client.request.duration")
        assert http_point.attributes["error.type"] == "ConnectError"
        assert "http.response.status_code" not in http_point.attributes

    async def test_no_identifiers_in_attributes(self, reader):
        async with Client(_server(reader)) as client:
            await client.call_tool("GetShell", {"aasIdentifier": AAS_ID})

        for name in ("mcp.server.operation.duration", "http.client.request.duration"):
            for point in _points(reader, name):
                for value in point.attributes.values():
                    assert AAS_ID not in str(value)
                    assert "/shells" not in str(value)

    async def test_rate_limited_requests(self, reader):
        limiter = RateLimitingMiddleware(
            max_requests_per_second=0.001, burst_capacity=1
        )
        async with Client(_server(reader, rate_limiter=limiter)) as client:
            # The first request spends the only token.
            with pytest.raises(MCPError, match="Rate limit exceeded"):
                await client.call_tool("GetShell", {"aasIdentifier": AAS_ID})

        [rejected] = [
            p
            for p in _points(reader, "aas_mcp.rate_limit.rejections")
            if p.attributes["mcp.method.name"] == "tools/call"
        ]
        assert rejected.value == 1
        [tool_point] = [
            p
            for p in _points(reader, "mcp.server.operation.duration")
            if p.attributes["mcp.method.name"] == "tools/call"
        ]
        assert tool_point.attributes["error.type"] == "RateLimitError"
        # Rejected before reaching the backend.
        assert _points(reader, "http.client.request.duration") == []


def test_error_type_uses_root_cause_class():
    try:
        try:
            raise ValueError("secret detail")
        except ValueError as inner:
            raise ToolError("wrapped") from inner
    except ToolError as exc:
        assert _error_type(exc) == "ValueError"


def test_error_type_for_rate_limit():
    assert _error_type(RateLimitError("Rate limit exceeded")) == "RateLimitError"


# ---------------------------------------------------------------------------
# Backend token cache hit/miss
# ---------------------------------------------------------------------------


def _lookups(reader) -> dict[str, int]:
    return {
        p.attributes["aas_mcp.cache.result"]: p.value
        for p in _points(reader, "aas_mcp.backend_token.cache.lookups")
        if p.attributes["aas_mcp.backend_auth.strategy"] == "token_exchange"
    }


@pytest.mark.asyncio
class TestTokenCacheMetrics:
    async def test_miss_then_hit(self, reader):
        cache = _KeyedTokenCache(strategy="token_exchange", meter=reader.meter)

        async def fetch():
            return ("tok", 3600)

        await cache.get_or_fetch("subject-a", fetch, label="test")
        await cache.get_or_fetch("subject-a", fetch, label="test")
        await cache.get_or_fetch("subject-b", fetch, label="test")

        assert _lookups(reader) == {"miss": 2, "hit": 1}

    async def test_coalesced_waiters_count_as_hits(self, reader):
        cache = _KeyedTokenCache(strategy="token_exchange", meter=reader.meter)
        release = asyncio.Event()

        async def fetch():
            await release.wait()
            return ("tok", 3600)

        first = asyncio.create_task(cache.get_or_fetch("k", fetch, label="test"))
        second = asyncio.create_task(cache.get_or_fetch("k", fetch, label="test"))
        await asyncio.sleep(0)
        release.set()
        assert await asyncio.gather(first, second) == ["tok", "tok"]

        assert _lookups(reader) == {"miss": 1, "hit": 1}

    async def test_cache_key_is_never_an_attribute(self, reader):
        cache = _KeyedTokenCache(strategy="token_exchange", meter=reader.meter)

        async def fetch():
            return ("tok", 3600)

        await cache.get_or_fetch("sha256-of-upstream-token", fetch, label="test")
        for point in _points(reader, "aas_mcp.backend_token.cache.lookups"):
            assert set(point.attributes) == {
                "aas_mcp.backend_auth.strategy",
                "aas_mcp.cache.result",
            }


# ---------------------------------------------------------------------------
# Wiring in build_mcp_server
# ---------------------------------------------------------------------------


class TestWiring:
    def _build(self, tracer_provider, meter_provider):
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
                return_value=tracer_provider,
            ),
            patch(
                "aas_mcp_server.server.configure_metrics",
                return_value=meter_provider,
            ),
            patch("aas_mcp_server.server.FastMCP") as fastmcp,
        ):
            build_mcp_server(component, base_url=BACKEND, enable_writes=False)
        return (
            build_client.call_args.kwargs,
            fastmcp.from_openapi.call_args.kwargs["middleware"],
        )

    def test_off_by_default(self):
        client_kwargs, middleware = self._build(None, None)
        assert "traced" not in client_kwargs
        assert not any(isinstance(m, MetricsMiddleware) for m in middleware)

    def test_metrics_only_instruments_client_and_adds_middleware_first(self):
        client_kwargs, middleware = self._build(None, object())
        assert client_kwargs["traced"] is True
        assert isinstance(middleware[0], MetricsMiddleware)
        assert any(isinstance(m, RateLimitingMiddleware) for m in middleware)

    def test_tracing_only_has_no_metrics_middleware(self):
        client_kwargs, middleware = self._build(object(), None)
        assert client_kwargs["traced"] is True
        assert not any(isinstance(m, MetricsMiddleware) for m in middleware)
