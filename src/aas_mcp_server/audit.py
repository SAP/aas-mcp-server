# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Structured, vendor-neutral audit logging for MCP tool calls (issue #132).

When enabled (``AUDIT_LOG_ENABLED=true``), every tool invocation produces one
JSON object on a single line:

    {"event": "tool_call", "timestamp": "...", "component": "aas-repo",
     "tool": "get_shell", "operation": "GET /shells/{aasIdentifier}",
     "access": "read", "resource_id": {"aasIdentifier": "..."},
     "subject": "user-123", "source": "mcp-client-id",
     "outcome": "success", "duration_ms": 12.3, "trace_id": null}

Design notes:

* Output is plain JSON lines so any collector (Fluentd, Vector, Loki,
  ``docker logs``...) can ingest it. No vendor SDK is involved.
* stdio-safe: on the stdio transport stdout carries the MCP protocol, so audit
  events go to stderr there. On HTTP transports they go to stdout.
* No secrets and no payloads: only the operation template (``{param}``
  placeholders, not filled-in URLs), path identifiers, the token subject and
  client id, and the outcome are recorded. Request bodies, query values,
  response bodies, token values and exception messages are never written.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, TextIO

import httpx2
import mcp.types as mt
from fastmcp.exceptions import NotFoundError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.middleware.rate_limiting import RateLimitError
from fastmcp.tools import Tool, ToolResult

from .constants import WRITE_METHODS

AUDIT_EVENT_TOOL_CALL = "tool_call"

ACCESS_READ = "read"
ACCESS_WRITE = "write"

OUTCOME_SUCCESS = "success"
OUTCOME_DENIED = "denied"
OUTCOME_ERROR = "error"

# Backend responses that mean "the caller is not allowed", as opposed to a fault.
DENIED_HTTP_STATUSES = frozenset({401, 403})

PARAM_LOCATION_PATH = "path"


class ToolOperation:
    """What an MCP tool maps to on the AAS backend."""

    __slots__ = ("method", "path", "path_params")

    def __init__(self, method: str, path: str, path_params: tuple[str, ...]):
        self.method = method.upper()
        self.path = path
        self.path_params = path_params

    @property
    def access(self) -> str:
        return ACCESS_WRITE if self.method.lower() in WRITE_METHODS else ACCESS_READ

    @property
    def operation(self) -> str:
        return f"{self.method} {self.path}"


class ToolOperationIndex:
    """Maps generated tool names to backend operations.

    FastMCP derives tool names from operationIds (aliasing, slugifying,
    truncating, de-duplicating). Rather than re-implementing that, the index is
    filled through ``FastMCP.from_openapi(mcp_component_fn=...)``, which is
    called with the final tool name and its route.
    """

    def __init__(self) -> None:
        self._operations: dict[str, ToolOperation] = {}

    def record(self, route: Any, component: Any) -> None:
        """``mcp_component_fn`` hook: remember the route behind each tool."""
        if not isinstance(component, Tool):
            return
        path_params = tuple(
            p.name
            for p in getattr(route, "parameters", [])
            if getattr(p, "location", None) == PARAM_LOCATION_PATH
        )
        self._operations[component.name] = ToolOperation(
            method=str(route.method), path=route.path, path_params=path_params
        )

    def get(self, tool_name: str) -> ToolOperation | None:
        return self._operations.get(tool_name)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _current_identity() -> tuple[str | None, str | None]:
    """Return (subject, client_id) of the authenticated caller, if any."""
    try:
        token = get_access_token()
    except Exception:  # no request context (e.g. stdio without auth)
        return None, None
    if token is None:
        return None, None
    claims = getattr(token, "claims", None) or {}
    subject = claims.get("sub")
    return (str(subject) if subject is not None else None), token.client_id


def _exception_chain(exc: BaseException) -> list[BaseException]:
    """The exception and its causes (FastMCP wraps backend errors in ToolError)."""
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _classify_exception(exc: BaseException) -> tuple[str, dict[str, Any]]:
    """Return (outcome, extra fields) for a failed tool call."""
    chain = _exception_chain(exc)
    for item in chain:
        if isinstance(item, (RateLimitError, NotFoundError)):
            return OUTCOME_DENIED, {"reason": type(item).__name__}
        if isinstance(item, httpx2.HTTPStatusError):
            status = item.response.status_code
            outcome = (
                OUTCOME_DENIED if status in DENIED_HTTP_STATUSES else OUTCOME_ERROR
            )
            return outcome, {"status_code": status}
    # Only the root cause's type (FastMCP's ToolError wrapper says nothing);
    # messages are never logged because they can contain backend URLs or data.
    return OUTCOME_ERROR, {"error_type": type(chain[-1]).__name__}


# Marks an exception already written by on_call_tool, so the outer on_request
# hook does not log the same call twice.
_AUDITED_ATTR = "_aas_mcp_audited"
MCP_METHOD_TOOLS_CALL = "tools/call"


class AuditMiddleware(Middleware):
    """Emit one structured audit event per MCP tool call."""

    def __init__(
        self,
        component_name: str,
        operation_index: ToolOperationIndex,
        transport: str = "stdio",
        stream_factory: Callable[[], TextIO] | None = None,
    ) -> None:
        self.component_name = component_name
        self.operation_index = operation_index
        self.transport = transport
        # Resolved per event so redirected/replaced streams are honoured.
        self._stream_factory = stream_factory or self._default_stream

    def _default_stream(self) -> TextIO:
        # stdout is the MCP protocol channel on stdio; never write there.
        return sys.stderr if self.transport == "stdio" else sys.stdout

    def _emit(self, event: dict[str, Any]) -> None:
        stream = self._stream_factory()
        stream.write(json.dumps(event, separators=(",", ":"), default=str) + "\n")
        stream.flush()

    def _base_event(
        self, tool_name: str, arguments: dict[str, Any] | None
    ) -> dict[str, Any]:
        op = self.operation_index.get(tool_name)
        subject, client_id = _current_identity()
        resource_id: dict[str, str] | None = None
        if op is not None and op.path_params and arguments:
            resource_id = {
                name: str(arguments[name])
                for name in op.path_params
                if arguments.get(name) is not None
            } or None
        return {
            "event": AUDIT_EVENT_TOOL_CALL,
            "timestamp": _utc_timestamp(),
            "component": self.component_name,
            "tool": tool_name,
            "operation": op.operation if op else None,
            "access": op.access if op else None,
            "resource_id": resource_id,
            "subject": subject,
            "source": client_id,
            # Filled in once OpenTelemetry tracing lands (#133).
            "trace_id": None,
        }

    async def on_request(self, context: MiddlewareContext, call_next: CallNext) -> Any:
        """Record tool calls rejected before they reach the tool layer.

        FastMCP runs request-level middleware such as ``RateLimitingMiddleware``
        in an outer pass, so a rate-limited call never reaches
        :meth:`on_call_tool`. Those rejections are recorded here.
        """
        started = time.perf_counter()
        try:
            return await call_next(context)
        except Exception as exc:
            if context.method == MCP_METHOD_TOOLS_CALL and not getattr(
                exc, _AUDITED_ATTR, False
            ):
                message = context.message
                event = self._base_event(
                    getattr(message, "name", None) or "",
                    getattr(message, "arguments", None),
                )
                outcome, extra = _classify_exception(exc)
                event.update(extra)
                event["outcome"] = outcome
                event["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
                self._emit(event)
            raise

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name = context.message.name
        event = self._base_event(tool_name, context.message.arguments)
        started = time.perf_counter()
        try:
            result = await call_next(context)
        except Exception as exc:
            outcome, extra = _classify_exception(exc)
            event.update(extra)
            event["outcome"] = outcome
            event["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
            self._emit(event)
            try:
                setattr(exc, _AUDITED_ATTR, True)
            except AttributeError:  # pragma: no cover - exotic exception types
                pass
            raise
        event["outcome"] = OUTCOME_SUCCESS
        event["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
        self._emit(event)
        return result
