# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for structured audit logging (issue #132).

The tool calls run end-to-end through a real FastMCP server generated from a
small OpenAPI spec, with the AAS backend replaced by an httpx2 MockTransport.
"""

import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx2
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware

import aas_mcp_server.audit as audit
from aas_mcp_server.audit import AuditMiddleware, ToolOperationIndex
from aas_mcp_server.constants import ENV_AUDIT_LOG_ENABLED
from aas_mcp_server.server import build_mcp_server

AAS_ID = "aHR0cHM6Ly9leGFtcGxlLmNvbS9hYXMvMQ"
SECRET_BODY_VALUE = "do-not-log-this-body-value"

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
            },
            "put": {
                "operationId": "PutShell",
                "parameters": [
                    {
                        "name": "aasIdentifier",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"idShort": {"type": "string"}},
                            }
                        }
                    }
                },
                "responses": {"204": {"description": "updated"}},
            },
        },
        "/shells": {
            "get": {
                "operationId": "GetAllShells",
                "responses": {"200": {"description": "ok"}},
            }
        },
    },
}


def _backend(status: int = 200):
    def handler(request: httpx2.Request) -> httpx2.Response:
        if status == 204 or request.method == "PUT":
            return httpx2.Response(204)
        return httpx2.Response(status, json={"id": "x"})

    return handler


def _server(stream: io.StringIO, status: int = 200, extra_middleware=None):
    index = ToolOperationIndex()
    client = httpx2.AsyncClient(
        base_url="http://backend.invalid",
        transport=httpx2.MockTransport(_backend(status)),
    )
    middleware = [
        AuditMiddleware(
            component_name="aas-repo",
            operation_index=index,
            transport="http",
            stream_factory=lambda: stream,
        ),
        *(extra_middleware or []),
    ]
    return FastMCP.from_openapi(
        openapi_spec=SPEC,
        client=client,
        middleware=middleware,
        mask_error_details=True,
        mcp_component_fn=index.record,
    )


def _events(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


async def _call(server, tool, args=None):
    async with Client(server) as c:
        return await c.call_tool(tool, args or {})


@pytest.fixture
def no_identity(monkeypatch):
    monkeypatch.setattr(audit, "get_access_token", lambda: None)


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_identity")
class TestOutcomes:
    async def test_successful_read(self):
        stream = io.StringIO()
        await _call(_server(stream), "GetShell", {"aasIdentifier": AAS_ID})

        [event] = _events(stream)
        assert event["event"] == "tool_call"
        assert event["component"] == "aas-repo"
        assert event["tool"] == "GetShell"
        assert event["operation"] == "GET /shells/{aasIdentifier}"
        assert event["access"] == "read"
        assert event["resource_id"] == {"aasIdentifier": AAS_ID}
        assert event["outcome"] == "success"
        assert event["trace_id"] is None
        assert isinstance(event["duration_ms"], float)
        assert event["timestamp"].endswith("+00:00")

    async def test_write_is_marked_and_body_is_not_logged(self):
        stream = io.StringIO()
        await _call(
            _server(stream),
            "PutShell",
            {"aasIdentifier": AAS_ID, "idShort": SECRET_BODY_VALUE},
        )

        [event] = _events(stream)
        assert event["access"] == "write"
        assert event["operation"] == "PUT /shells/{aasIdentifier}"
        assert event["outcome"] == "success"
        assert SECRET_BODY_VALUE not in stream.getvalue()

    async def test_operation_without_path_params_has_no_resource_id(self):
        stream = io.StringIO()
        await _call(_server(stream), "GetAllShells")

        [event] = _events(stream)
        assert event["resource_id"] is None
        assert event["operation"] == "GET /shells"

    @pytest.mark.parametrize("status", [401, 403])
    async def test_backend_auth_rejection_is_denied(self, status):
        stream = io.StringIO()
        with pytest.raises(ToolError):
            await _call(
                _server(stream, status=status), "GetShell", {"aasIdentifier": AAS_ID}
            )

        [event] = _events(stream)
        assert event["outcome"] == "denied"
        assert event["status_code"] == status

    async def test_backend_failure_is_error(self):
        stream = io.StringIO()
        with pytest.raises(ToolError):
            await _call(
                _server(stream, status=500), "GetShell", {"aasIdentifier": AAS_ID}
            )

        [event] = _events(stream)
        assert event["outcome"] == "error"
        assert event["status_code"] == 500
        assert "backend.invalid" not in stream.getvalue()

    async def test_tool_outside_curated_surface_is_denied(self):
        stream = io.StringIO()
        with pytest.raises(ToolError):
            await _call(_server(stream), "DeleteShell", {"aasIdentifier": AAS_ID})

        [event] = _events(stream)
        assert event["tool"] == "DeleteShell"
        assert event["operation"] is None
        assert event["outcome"] == "denied"
        assert event["reason"] == "NotFoundError"

    async def test_rate_limited_call_is_denied(self):
        stream = io.StringIO()
        limiter = RateLimitingMiddleware(
            max_requests_per_second=0.001, burst_capacity=10, global_limit=True
        )
        server = _server(stream, extra_middleware=[limiter])
        async with Client(server) as c:
            await c.call_tool("GetAllShells", {})
            limiter.global_limiter.tokens = 0  # exhaust the bucket
            with pytest.raises(Exception, match="rate limit"):
                await c.call_tool("GetAllShells", {})

        events = _events(stream)
        assert [e["outcome"] for e in events] == ["success", "denied"]
        assert events[1]["reason"] == "RateLimitError"

    async def test_unexpected_exception_logs_type_only(self):
        stream = io.StringIO()
        mw = AuditMiddleware(
            "aas-repo", ToolOperationIndex(), stream_factory=lambda: stream
        )
        context = SimpleNamespace(message=SimpleNamespace(name="t", arguments={}))

        async def boom(_ctx):
            raise ValueError("http://internal-host/secret-path")

        with pytest.raises(ValueError):
            await mw.on_call_tool(context, boom)

        [event] = _events(stream)
        assert event["outcome"] == "error"
        assert event["error_type"] == "ValueError"
        assert "internal-host" not in stream.getvalue()


@pytest.mark.asyncio
class TestIdentity:
    async def test_subject_and_client_from_access_token(self, monkeypatch):
        token = SimpleNamespace(
            claims={"sub": "user-123", "email": "u@example.com"},
            client_id="mcp-client-1",
            token="secret-token-value",
        )
        monkeypatch.setattr(audit, "get_access_token", lambda: token)
        stream = io.StringIO()
        await _call(_server(stream), "GetAllShells")

        [event] = _events(stream)
        assert event["subject"] == "user-123"
        assert event["source"] == "mcp-client-1"
        assert "secret-token-value" not in stream.getvalue()
        assert "u@example.com" not in stream.getvalue()

    async def test_anonymous_call(self, no_identity):
        stream = io.StringIO()
        await _call(_server(stream), "GetAllShells")

        [event] = _events(stream)
        assert event["subject"] is None
        assert event["source"] is None


class TestOutputStream:
    def test_stdio_transport_writes_to_stderr(self, capsys):
        mw = AuditMiddleware("aas-repo", ToolOperationIndex(), transport="stdio")
        mw._emit({"event": "tool_call"})
        out, err = capsys.readouterr()
        assert out == ""
        assert json.loads(err) == {"event": "tool_call"}

    def test_http_transport_writes_to_stdout(self, capsys):
        mw = AuditMiddleware("aas-repo", ToolOperationIndex(), transport="http")
        mw._emit({"event": "tool_call"})
        out, err = capsys.readouterr()
        assert err == ""
        assert json.loads(out) == {"event": "tool_call"}


class TestBuildMcpServerWiring:
    def _build(self, mock_fastmcp_class):
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
            patch("aas_mcp_server.server.build_async_client"),
            patch("aas_mcp_server.server.FastMCP", mock_fastmcp_class),
        ):
            build_mcp_server(component, base_url="http://x", enable_writes=False)
        return mock_fastmcp_class.from_openapi.call_args.kwargs

    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv(ENV_AUDIT_LOG_ENABLED, raising=False)
        kwargs = self._build(MagicMock())
        assert not any(isinstance(m, AuditMiddleware) for m in kwargs["middleware"])
        assert "mcp_component_fn" not in kwargs

    def test_enabled_runs_before_rate_limiter(self, monkeypatch):
        monkeypatch.setenv(ENV_AUDIT_LOG_ENABLED, "true")
        kwargs = self._build(MagicMock())
        middleware = kwargs["middleware"]
        assert isinstance(middleware[0], AuditMiddleware)
        assert isinstance(middleware[1], RateLimitingMiddleware)
        assert kwargs["mcp_component_fn"] == middleware[0].operation_index.record

    def test_invalid_value_is_rejected(self, monkeypatch):
        monkeypatch.setenv(ENV_AUDIT_LOG_ENABLED, "maybe")
        with pytest.raises(ValueError, match=ENV_AUDIT_LOG_ENABLED):
            self._build(MagicMock())


@pytest.mark.asyncio
async def test_wrapped_exception_reports_root_cause_type():
    stream = io.StringIO()
    mw = AuditMiddleware(
        "aas-repo", ToolOperationIndex(), stream_factory=lambda: stream
    )
    context = SimpleNamespace(message=SimpleNamespace(name="t", arguments={}))

    async def wrapped(_ctx):
        try:
            raise ConnectionRefusedError("connect to 10.0.0.5:8081 refused")
        except ConnectionRefusedError as exc:
            raise ToolError("Error calling tool 't'") from exc

    with pytest.raises(ToolError):
        await mw.on_call_tool(context, wrapped)

    [event] = _events(stream)
    assert event["error_type"] == "ConnectionRefusedError"
    assert "10.0.0.5" not in stream.getvalue()


def test_index_ignores_non_tool_components():
    index = ToolOperationIndex()
    route = SimpleNamespace(method="GET", path="/shells", parameters=[])
    index.record(route, SimpleNamespace(name="a-resource"))
    assert index.get("a-resource") is None


@pytest.mark.asyncio
async def test_identity_lookup_failure_is_anonymous(monkeypatch):
    def no_context():
        raise RuntimeError("no active request")

    monkeypatch.setattr(audit, "get_access_token", no_context)
    stream = io.StringIO()
    await _call(_server(stream), "GetAllShells")

    [event] = _events(stream)
    assert event["subject"] is None
    assert event["source"] is None
    assert event["outcome"] == "success"
