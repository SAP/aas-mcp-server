# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for RetryTransport (bounded exponential-backoff retries for GET/HEAD).

All tests use httpx2.MockTransport(callable) — same pattern as test_tracing.py.
asyncio.sleep is patched to make tests deterministic and instant.
"""

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import pytest

from aas_mcp_server.retry_transport import RetryTransport, _parse_retry_after


# ---------------------------------------------------------------------------
# Shared test infrastructure
# ---------------------------------------------------------------------------


class _Backend:
    """Callable backend that plays back a sequence of responses or exceptions."""

    def __init__(self, responses):
        self._responses = iter(responses)
        self.call_count = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.call_count += 1
        item = next(self._responses)
        if isinstance(item, Exception):
            raise item
        return item


def _transport(responses, max_retries=3, budget=30.0):
    backend = _Backend(responses)
    return RetryTransport(httpx2.MockTransport(backend), max_retries=max_retries, budget=budget), backend


def _request(method="GET", url="http://test/shells"):
    return httpx2.Request(method, url)


# ---------------------------------------------------------------------------
# Success path — no retries needed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_on_first_attempt_no_retry():
    transport, backend = _transport([httpx2.Response(200)])
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        resp = await transport.handle_async_request(_request())
    assert resp.status_code == 200
    assert backend.call_count == 1
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Non-safe methods are never retried
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
async def test_non_safe_methods_not_retried(method):
    transport, backend = _transport([httpx2.Response(503)])
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        resp = await transport.handle_async_request(_request(method=method))
    assert resp.status_code == 503
    assert backend.call_count == 1
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# ConnectError / RemoteProtocolError retries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retries_on_connect_error_then_success():
    transport, backend = _transport([
        httpx2.ConnectError("refused"),
        httpx2.ConnectError("refused"),
        httpx2.Response(200),
    ])
    with patch("asyncio.sleep", new_callable=AsyncMock):
        resp = await transport.handle_async_request(_request())
    assert resp.status_code == 200
    assert backend.call_count == 3


@pytest.mark.asyncio
async def test_retries_on_remote_protocol_error():
    transport, backend = _transport([
        httpx2.RemoteProtocolError("peer closed"),
        httpx2.Response(200),
    ])
    with patch("asyncio.sleep", new_callable=AsyncMock):
        resp = await transport.handle_async_request(_request())
    assert resp.status_code == 200
    assert backend.call_count == 2


@pytest.mark.asyncio
async def test_connect_error_exhausted_reraises():
    transport, backend = _transport([
        httpx2.ConnectError("refused"),
        httpx2.ConnectError("refused"),
        httpx2.ConnectError("refused"),
        httpx2.ConnectError("refused"),  # attempt 3 (index=3) == max_retries=3 → raise
    ], max_retries=3)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(httpx2.ConnectError):
            await transport.handle_async_request(_request())
    assert backend.call_count == 4  # initial + 3 retries


# ---------------------------------------------------------------------------
# HTTP status code retries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [502, 503, 504])
async def test_retries_on_transient_status_codes(status):
    transport, backend = _transport([
        httpx2.Response(status),
        httpx2.Response(200),
    ])
    with patch("asyncio.sleep", new_callable=AsyncMock):
        resp = await transport.handle_async_request(_request())
    assert resp.status_code == 200
    assert backend.call_count == 2


@pytest.mark.asyncio
async def test_transient_status_exhausted_returns_last_response():
    transport, backend = _transport([
        httpx2.Response(503),
        httpx2.Response(503),
        httpx2.Response(503),
        httpx2.Response(503),  # attempt 3 == max_retries → return
    ], max_retries=3)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        resp = await transport.handle_async_request(_request())
    assert resp.status_code == 503
    assert backend.call_count == 4


@pytest.mark.asyncio
async def test_non_retryable_status_returned_immediately():
    transport, backend = _transport([httpx2.Response(500)])
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        resp = await transport.handle_async_request(_request())
    assert resp.status_code == 500
    assert backend.call_count == 1
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# max_retries=0 disables all retries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_retries_zero_disables_on_exception():
    transport, backend = _transport(
        [httpx2.ConnectError("refused")], max_retries=0
    )
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(httpx2.ConnectError):
            await transport.handle_async_request(_request())
    assert backend.call_count == 1
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_max_retries_zero_disables_on_status():
    transport, backend = _transport([httpx2.Response(503)], max_retries=0)
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        resp = await transport.handle_async_request(_request())
    assert resp.status_code == 503
    assert backend.call_count == 1
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_exhausted_stops_on_exception():
    transport, backend = _transport(
        [httpx2.ConnectError("refused"), httpx2.Response(200)],
        max_retries=3,
        budget=0.0,
    )
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(httpx2.ConnectError):
            await transport.handle_async_request(_request())
    assert backend.call_count == 1
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_budget_exhausted_stops_on_status():
    transport, backend = _transport(
        [httpx2.Response(503), httpx2.Response(200)],
        max_retries=3,
        budget=0.0,
    )
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        resp = await transport.handle_async_request(_request())
    assert resp.status_code == 503
    assert backend.call_count == 1
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Retry-After header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_after_integer_used_as_delay():
    transport, backend = _transport([
        httpx2.Response(503, headers={"retry-after": "5"}),
        httpx2.Response(200),
    ])
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        resp = await transport.handle_async_request(_request())
    assert resp.status_code == 200
    mock_sleep.assert_called_once()
    assert mock_sleep.call_args[0][0] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_retry_after_httpdate_used_as_delay():
    future_ts = time.time() + 10
    http_date = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(future_ts))
    transport, backend = _transport([
        httpx2.Response(503, headers={"retry-after": http_date}),
        httpx2.Response(200),
    ])
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        resp = await transport.handle_async_request(_request())
    assert resp.status_code == 200
    mock_sleep.assert_called_once()
    # Allow some clock skew
    assert 8.0 <= mock_sleep.call_args[0][0] <= 11.0


@pytest.mark.asyncio
async def test_retry_after_capped_at_max_wait():
    transport, backend = _transport([
        httpx2.Response(503, headers={"retry-after": "120"}),  # > 60s cap
        httpx2.Response(200),
    ], budget=120.0)  # budget > cap so only _RETRY_AFTER_MAX_WAIT kicks in
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        resp = await transport.handle_async_request(_request())
    assert resp.status_code == 200
    assert mock_sleep.call_args[0][0] == pytest.approx(60.0)


@pytest.mark.asyncio
async def test_retry_after_capped_at_budget():
    transport, backend = _transport([
        httpx2.Response(503, headers={"retry-after": "10"}),
        httpx2.Response(200),
    ], budget=5.0)
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        resp = await transport.handle_async_request(_request())
    assert resp.status_code == 200
    assert mock_sleep.call_args[0][0] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# aclose delegates to inner transport
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aclose_delegates():
    inner = MagicMock()
    inner.aclose = AsyncMock()
    transport = RetryTransport(inner)
    await transport.aclose()
    inner.aclose.assert_called_once()


# ---------------------------------------------------------------------------
# _parse_retry_after unit tests
# ---------------------------------------------------------------------------


def test_parse_retry_after_integer():
    assert _parse_retry_after("30") == 30.0


def test_parse_retry_after_integer_with_whitespace():
    assert _parse_retry_after("  10  ") == 10.0


def test_parse_retry_after_httpdate():
    future_ts = time.time() + 20
    http_date = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(future_ts))
    result = _parse_retry_after(http_date)
    assert result is not None
    assert 18.0 <= result <= 21.0


def test_parse_retry_after_past_httpdate_returns_zero():
    past_ts = time.time() - 60
    http_date = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(past_ts))
    result = _parse_retry_after(http_date)
    assert result == 0.0


def test_parse_retry_after_invalid_returns_none():
    assert _parse_retry_after("not-a-date") is None


def test_parse_retry_after_empty_returns_none():
    assert _parse_retry_after("") is None


# ---------------------------------------------------------------------------
# build_async_client integration: AAS_HTTP_MAX_RETRIES env var
# ---------------------------------------------------------------------------


def test_build_async_client_default_max_retries():
    """RetryTransport is wired with default max_retries when env var absent."""
    from aas_mcp_server.http_client import build_async_client
    from aas_mcp_server.constants import DEFAULT_HTTP_MAX_RETRIES

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AAS_HTTP_MAX_RETRIES", None)
        client = build_async_client("http://localhost:8080")

    assert isinstance(client._transport, RetryTransport)
    assert client._transport._max_retries == DEFAULT_HTTP_MAX_RETRIES


def test_build_async_client_max_retries_zero():
    """AAS_HTTP_MAX_RETRIES=0 wires RetryTransport with max_retries=0 (disabled)."""
    from aas_mcp_server.http_client import build_async_client

    with patch.dict(os.environ, {"AAS_HTTP_MAX_RETRIES": "0"}):
        client = build_async_client("http://localhost:8080")

    assert isinstance(client._transport, RetryTransport)
    assert client._transport._max_retries == 0


def test_build_async_client_invalid_max_retries_raises():
    from aas_mcp_server.http_client import build_async_client

    with patch.dict(os.environ, {"AAS_HTTP_MAX_RETRIES": "abc"}):
        with pytest.raises(ValueError, match="AAS_HTTP_MAX_RETRIES"):
            build_async_client("http://localhost:8080")


def test_build_async_client_negative_max_retries_raises():
    from aas_mcp_server.http_client import build_async_client

    with patch.dict(os.environ, {"AAS_HTTP_MAX_RETRIES": "-1"}):
        with pytest.raises(ValueError, match="AAS_HTTP_MAX_RETRIES"):
            build_async_client("http://localhost:8080")
