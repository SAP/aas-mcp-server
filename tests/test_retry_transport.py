# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for RetryTransport (bounded exponential-backoff retries for GET/HEAD).

All tests use httpx2.MockTransport(callable) — same pattern as test_tracing.py.
asyncio.sleep is patched to make tests deterministic and instant.
time.monotonic is patched where deadline behaviour is under test.
"""

import asyncio
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
        self.closed: list[int] = []  # status codes of responses that were aclose()d

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.call_count += 1
        item = next(self._responses)
        if isinstance(item, Exception):
            raise item
        return item


def _transport(responses, max_retries=3, budget=30.0):
    backend = _Backend(responses)
    transport = RetryTransport(httpx2.MockTransport(backend), max_retries=max_retries, budget=budget)
    return transport, backend


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
# Monotonic deadline — accounts for request execution time, not just sleep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deadline_stops_retry_when_budget_elapsed_during_request():
    """Budget consumed entirely by request time (no sleep remaining) stops retries."""
    # Simulate: deadline already passed by the time we check it after the request.
    # We freeze monotonic so that after the first request, the deadline is in the past.
    t0 = 1000.0
    # deadline = t0 + 30.0 = 1030.0
    # After first request (simulated elapsed=31s): monotonic() returns 1031.0
    # _delay returns min(0.5+jitter, 1031.0 - 1030.0) = negative → stop
    monotonic_values = iter([t0, t0 + 31.0])  # one for deadline init, one for _delay check

    with patch("aas_mcp_server.retry_transport.time.monotonic", side_effect=monotonic_values):
        transport, backend = _transport(
            [httpx2.ConnectError("refused"), httpx2.Response(200)],
            max_retries=3,
            budget=30.0,
        )
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(httpx2.ConnectError):
                await transport.handle_async_request(_request())

    assert backend.call_count == 1
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_deadline_stops_status_retry_when_budget_elapsed_during_request():
    """Same as above but for a retryable status code (503) path."""
    t0 = 1000.0
    monotonic_values = iter([t0, t0 + 31.0])

    with patch("aas_mcp_server.retry_transport.time.monotonic", side_effect=monotonic_values):
        transport, backend = _transport(
            [httpx2.Response(503), httpx2.Response(200)],
            max_retries=3,
            budget=30.0,
        )
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            resp = await transport.handle_async_request(_request())

    # Budget elapsed: returns the last (503) response without retrying.
    assert resp.status_code == 503
    assert backend.call_count == 1
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Budget enforcement (sleep-based, legacy behaviour preserved)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backoff_not_shortened_to_fit_budget():
    """Backoff delay that exceeds the remaining budget skips the retry (not shortened)."""
    # budget=1.0 → deadline = monotonic() + 1.0
    # First request completes. _delay computes raw ≈ 0.5 (attempt=0).
    # We freeze monotonic so budget_remaining = 0.3 < raw ≈ 0.5 → skip retry.
    t0 = 1000.0
    # Call sequence: [deadline init, _delay budget check]
    monotonic_values = iter([t0, t0 + 0.7])  # 1s budget, 0.7s elapsed → 0.3s remaining

    with patch("aas_mcp_server.retry_transport.time.monotonic", side_effect=monotonic_values):
        transport, backend = _transport(
            [httpx2.ConnectError("refused"), httpx2.Response(200)],
            max_retries=3,
            budget=1.0,
        )
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(httpx2.ConnectError):
                await transport.handle_async_request(_request())

    # Retry skipped: not called with a shortened delay.
    mock_sleep.assert_not_called()
    assert backend.call_count == 1


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
# Response cleanup — discarded responses must be closed before retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discarded_response_is_closed_before_retry():
    """A 503 response that triggers a retry must have aclose() called on it."""
    discarded = httpx2.Response(503)
    final = httpx2.Response(200)
    transport, backend = _transport([discarded, final])

    with patch.object(discarded, "aclose", new_callable=AsyncMock) as mock_close:
        with patch("asyncio.sleep", new_callable=AsyncMock):
            resp = await transport.handle_async_request(_request())

    assert resp.status_code == 200
    mock_close.assert_called_once()


@pytest.mark.asyncio
async def test_final_response_not_closed():
    """The final response (returned to caller) must NOT be closed."""
    discarded = httpx2.Response(503)
    final = httpx2.Response(200)
    transport, backend = _transport([discarded, final])

    with patch.object(final, "aclose", new_callable=AsyncMock) as mock_close:
        with patch("asyncio.sleep", new_callable=AsyncMock):
            resp = await transport.handle_async_request(_request())

    assert resp.status_code == 200
    mock_close.assert_not_called()


@pytest.mark.asyncio
async def test_exhausted_final_503_not_closed():
    """When retries are exhausted, the last 503 is returned (not closed)."""
    responses = [httpx2.Response(503), httpx2.Response(503)]
    transport, backend = _transport(responses, max_retries=1)
    final = responses[-1]

    with patch.object(final, "aclose", new_callable=AsyncMock) as mock_close:
        with patch("asyncio.sleep", new_callable=AsyncMock):
            resp = await transport.handle_async_request(_request())

    assert resp.status_code == 503
    mock_close.assert_not_called()


@pytest.mark.asyncio
async def test_multiple_discarded_responses_all_closed():
    """Each intermediate 503 is closed exactly once before the next attempt."""
    r1 = httpx2.Response(503)
    r2 = httpx2.Response(502)
    r3 = httpx2.Response(200)
    transport, backend = _transport([r1, r2, r3], max_retries=3)

    with (
        patch.object(r1, "aclose", new_callable=AsyncMock) as mc1,
        patch.object(r2, "aclose", new_callable=AsyncMock) as mc2,
        patch.object(r3, "aclose", new_callable=AsyncMock) as mc3,
        patch("asyncio.sleep", new_callable=AsyncMock),
    ):
        resp = await transport.handle_async_request(_request())

    assert resp.status_code == 200
    mc1.assert_called_once()
    mc2.assert_called_once()
    mc3.assert_not_called()


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
    """Retry-After exceeding _RETRY_AFTER_MAX_WAIT skips the retry (not truncated)."""
    transport, backend = _transport([
        httpx2.Response(503, headers={"retry-after": "120"}),  # > 60s cap
        httpx2.Response(200),
    ], budget=120.0)
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        resp = await transport.handle_async_request(_request())
    # Retry skipped — returns the 503 without retrying.
    assert resp.status_code == 503
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_retry_after_exceeds_budget_skips_retry():
    """Retry-After exceeding remaining budget skips the retry (not truncated)."""
    transport, backend = _transport([
        httpx2.Response(503, headers={"retry-after": "10"}),
        httpx2.Response(200),
    ], budget=5.0)
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        resp = await transport.handle_async_request(_request())
    # Retry skipped — returns the 503 without retrying.
    assert resp.status_code == 503
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_retry_after_zero_retries_immediately():
    """Retry-After: 0 (or a past date) means retry immediately — asyncio.sleep(0) is called."""
    transport, backend = _transport([
        httpx2.Response(503, headers={"retry-after": "0"}),
        httpx2.Response(200),
    ])
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        resp = await transport.handle_async_request(_request())
    assert resp.status_code == 200
    mock_sleep.assert_called_once()
    assert mock_sleep.call_args[0][0] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_retry_after_past_date_retries_immediately():
    """A past Retry-After date resolves to delay=0 and retries immediately."""
    past_ts = time.time() - 60
    http_date = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(past_ts))
    transport, backend = _transport([
        httpx2.Response(503, headers={"retry-after": http_date}),
        httpx2.Response(200),
    ])
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        resp = await transport.handle_async_request(_request())
    assert resp.status_code == 200
    mock_sleep.assert_called_once()
    assert mock_sleep.call_args[0][0] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Cancellation — CancelledError must not be swallowed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelled_error_propagates_during_request():
    """asyncio.CancelledError raised by the transport must propagate immediately."""
    async def _cancelled_transport(request):
        raise asyncio.CancelledError()

    inner = MagicMock()
    inner.handle_async_request = _cancelled_transport
    transport = RetryTransport(inner, max_retries=3)

    with pytest.raises(asyncio.CancelledError):
        await transport.handle_async_request(_request())


@pytest.mark.asyncio
async def test_cancelled_error_propagates_during_sleep():
    """CancelledError raised by asyncio.sleep must propagate without further retries."""
    transport, backend = _transport([
        httpx2.ConnectError("refused"),
        httpx2.Response(200),
    ], max_retries=3)

    async def _raise_cancelled(delay):
        raise asyncio.CancelledError()

    with patch("asyncio.sleep", side_effect=_raise_cancelled):
        with pytest.raises(asyncio.CancelledError):
            await transport.handle_async_request(_request())

    # Only one request was made before the sleep was cancelled.
    assert backend.call_count == 1


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


def test_parse_retry_after_zero():
    assert _parse_retry_after("0") == 0.0


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
# Logs must not contain URL paths (AAS paths carry sensitive identifiers)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_log_does_not_contain_url_path(caplog):
    import logging
    transport, backend = _transport([
        httpx2.ConnectError("refused"),
        httpx2.Response(200),
    ], max_retries=1)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        with caplog.at_level(logging.DEBUG, logger="aas_mcp_server.retry_transport"):
            await transport.handle_async_request(
                _request(url="http://test/shells/aHR0cHM6Ly9leGFtcGxlLmNvbQ==")
            )
    for record in caplog.records:
        assert "/shells/" not in record.message
        assert "aHR0" not in record.message  # base64 AAS identifier fragment


# ---------------------------------------------------------------------------
# build_async_client integration: proxy env vars preserved and retry wired
# ---------------------------------------------------------------------------


def test_build_async_client_uses_mounts_not_transport():
    """RetryTransport is wired via mounts= so env proxy vars remain active."""
    from aas_mcp_server.http_client import build_async_client

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AAS_HTTP_MAX_RETRIES", None)
        client = build_async_client("http://localhost:8080")

    # transport= is None — allow_env_proxies will be True in httpx2
    assert client._transport is not None  # default AsyncHTTPTransport
    # The "all://" mount holds our RetryTransport
    retry_mount = next(
        (t for pat, t in client._mounts.items() if pat.pattern == "all://"), None
    )
    assert retry_mount is not None
    assert isinstance(retry_mount, RetryTransport)


def test_build_async_client_default_max_retries():
    """RetryTransport is wired with default max_retries when env var absent."""
    from aas_mcp_server.http_client import build_async_client
    from aas_mcp_server.constants import DEFAULT_HTTP_MAX_RETRIES

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AAS_HTTP_MAX_RETRIES", None)
        client = build_async_client("http://localhost:8080")

    retry_mount = next(t for pat, t in client._mounts.items() if pat.pattern == "all://")
    assert isinstance(retry_mount, RetryTransport)
    assert retry_mount._max_retries == DEFAULT_HTTP_MAX_RETRIES


def test_build_async_client_max_retries_zero():
    """AAS_HTTP_MAX_RETRIES=0 wires RetryTransport with max_retries=0 (disabled)."""
    from aas_mcp_server.http_client import build_async_client

    with patch.dict(os.environ, {"AAS_HTTP_MAX_RETRIES": "0"}):
        client = build_async_client("http://localhost:8080")

    retry_mount = next(t for pat, t in client._mounts.items() if pat.pattern == "all://")
    assert isinstance(retry_mount, RetryTransport)
    assert retry_mount._max_retries == 0


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


def test_build_async_client_excessive_max_retries_raises():
    """AAS_HTTP_MAX_RETRIES > MAX_HTTP_MAX_RETRIES is rejected."""
    from aas_mcp_server.http_client import build_async_client
    from aas_mcp_server.constants import MAX_HTTP_MAX_RETRIES

    with patch.dict(os.environ, {"AAS_HTTP_MAX_RETRIES": str(MAX_HTTP_MAX_RETRIES + 1)}):
        with pytest.raises(ValueError, match="AAS_HTTP_MAX_RETRIES"):
            build_async_client("http://localhost:8080")


def test_build_async_client_transport_is_none_for_env_proxy_support():
    """client._transport must be None-free (default) so allow_env_proxies=True."""
    from aas_mcp_server.http_client import build_async_client

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("AAS_HTTP_MAX_RETRIES", None)
        client = build_async_client("http://localhost:8080")

    # httpx2 sets allow_env_proxies = trust_env and transport is None.
    # We pass mounts= not transport=, so _transport is the default AsyncHTTPTransport.
    assert isinstance(client._transport, httpx2.AsyncHTTPTransport)


def test_env_proxy_mounts_take_priority_over_retry_transport():
    """Requests via an env-proxy mount bypass RetryTransport (documented limitation).

    httpx2 adds more-specific proxy mounts (e.g. 'https://') that have higher
    priority than 'all://'.  Those requests are not retried.
    """
    from aas_mcp_server.http_client import build_async_client
    from aas_mcp_server.retry_transport import RetryTransport

    proxy_url = "http://proxy.example.com:3128"
    with patch.dict(os.environ, {"HTTPS_PROXY": proxy_url}):
        client = build_async_client("https://backend.example.com")

    # The more-specific 'https://' mount added by httpx2 should NOT be RetryTransport.
    https_mount = next(
        (t for pat, t in client._mounts.items() if pat.pattern == "https://"),
        None,
    )
    # The mount may or may not exist depending on httpx2 version; if it does,
    # it must not wrap RetryTransport (it's the raw proxy transport).
    if https_mount is not None:
        assert not isinstance(https_mount, RetryTransport)
