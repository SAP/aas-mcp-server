# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import email.utils
import logging
import random
import time

import httpx2

logger = logging.getLogger(__name__)

RETRY_STATUS_CODES = frozenset({502, 503, 504})
RETRY_EXCEPTIONS = (httpx2.ConnectError, httpx2.RemoteProtocolError)
SAFE_METHODS = frozenset({"GET", "HEAD"})
_RETRY_AFTER_MAX_WAIT = 60.0
_BASE_DELAY = 0.5


class RetryTransport(httpx2.AsyncBaseTransport):
    """Wraps a transport with bounded exponential-backoff retries for GET/HEAD.

    Retries ConnectError, RemoteProtocolError, and HTTP 502/503/504.
    Respects Retry-After on 503. Non-safe methods (POST/PUT/PATCH/DELETE) are
    never retried.

    Budget semantics: ``budget`` is a wall-clock deadline, set once before the
    first attempt.  A retry is started only if the calculated backoff delay fits
    entirely within the remaining time (i.e. ``delay <= deadline - now``).
    In-flight requests are not cancelled when the deadline passes; only the
    *start* of a new retry is gated.

    Retry-After semantics: if the server's Retry-After value exceeds
    ``_RETRY_AFTER_MAX_WAIT`` or the remaining budget the retry is skipped
    (the response is returned to the caller) rather than the delay being
    silently truncated.

    Configuration (via build_async_client / AAS_HTTP_MAX_RETRIES env var):
        max_retries: Maximum number of retry attempts after the first failure.
                     Set to 0 to disable retries entirely. Default: 2.
        budget:      Seconds from the first attempt before no new retry may
                     start.  Default: 30.0.
    """

    def __init__(
        self,
        transport: httpx2.AsyncBaseTransport,
        max_retries: int = 2,
        budget: float = 30.0,
    ) -> None:
        self._transport = transport
        self._max_retries = max_retries
        self._budget = budget

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if request.method.upper() not in SAFE_METHODS or self._max_retries == 0:
            return await self._transport.handle_async_request(request)

        # Monotonic deadline: accounts for both request execution time and backoff.
        deadline = time.monotonic() + self._budget
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._transport.handle_async_request(request)
            except RETRY_EXCEPTIONS as exc:
                if attempt == self._max_retries:
                    raise
                delay = self._delay(attempt, deadline)
                if delay < 0:
                    raise
                logger.debug(
                    "Retrying %s after %s (attempt %d/%d)",
                    request.method,
                    type(exc).__name__,
                    attempt + 1,
                    self._max_retries,
                )
                await asyncio.sleep(delay)
                continue

            if response.status_code not in RETRY_STATUS_CODES or attempt == self._max_retries:
                return response

            delay = self._retry_after_delay(response, attempt, deadline)
            if delay < 0:
                # Budget exhausted — return the last response rather than dropping it.
                return response
            logger.debug(
                "Retrying %s after HTTP %d (attempt %d/%d)",
                request.method,
                response.status_code,
                attempt + 1,
                self._max_retries,
            )
            # Close the discarded response to release its connection back to the pool.
            await response.aclose()
            await asyncio.sleep(delay)

        return response  # pragma: no cover

    def _delay(self, attempt: int, deadline: float) -> float:
        """Backoff delay if the full delay fits within the remaining budget.

        Returns the calculated delay if ``delay <= deadline - now``, otherwise
        returns a negative value so the caller stops retrying.  The delay is
        never shortened to fit the budget — if it doesn't fit, the retry is
        skipped entirely.
        """
        raw = _BASE_DELAY * (2**attempt) + random.uniform(0, 0.1)
        budget_remaining = deadline - time.monotonic()
        if raw > budget_remaining:
            return -1.0
        return raw

    def _retry_after_delay(
        self, response: httpx2.Response, attempt: int, deadline: float
    ) -> float:
        """Delay from Retry-After header, or exponential backoff.

        Returns the delay to sleep, or a negative value meaning skip this retry.
        A Retry-After delay that exceeds ``_RETRY_AFTER_MAX_WAIT`` or the
        remaining budget causes the retry to be skipped (response returned to
        caller) rather than the delay being silently truncated.
        A delay of 0.0 means retry immediately (past Retry-After date).
        """
        header = response.headers.get("retry-after")
        if header:
            parsed = _parse_retry_after(header)
            if parsed is not None:
                budget_remaining = deadline - time.monotonic()
                if parsed > _RETRY_AFTER_MAX_WAIT or parsed > budget_remaining:
                    # Server asked us to wait longer than we allow — skip retry.
                    return -1.0
                return parsed
        return self._delay(attempt, deadline)

    async def aclose(self) -> None:
        await self._transport.aclose()


def _parse_retry_after(value: str) -> float | None:
    """Parse Retry-After as integer seconds or HTTP-date. Returns None on failure."""
    stripped = value.strip()
    if stripped.isdigit():
        return float(stripped)
    try:
        dt = email.utils.parsedate_to_datetime(stripped)
        delay = dt.timestamp() - time.time()
        return max(0.0, delay)
    except ValueError:
        return None
