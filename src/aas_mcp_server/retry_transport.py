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
    Respects Retry-After on 503. Total retry budget prevents runaway waits.
    Non-idempotent methods (POST/PUT/PATCH/DELETE) are never retried.
    """

    def __init__(
        self,
        transport: httpx2.AsyncBaseTransport,
        max_retries: int = 3,
        budget: float = 30.0,
    ) -> None:
        self._transport = transport
        self._max_retries = max_retries
        self._budget = budget

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if request.method.upper() not in SAFE_METHODS or self._max_retries == 0:
            return await self._transport.handle_async_request(request)

        budget_remaining = self._budget
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._transport.handle_async_request(request)
            except RETRY_EXCEPTIONS as exc:
                if attempt == self._max_retries:
                    raise
                delay = self._delay(attempt, budget_remaining)
                if delay <= 0:
                    raise
                logger.debug(
                    "Retrying %s %s after %s (attempt %d/%d, budget %.1fs)",
                    request.method,
                    request.url.path,
                    type(exc).__name__,
                    attempt + 1,
                    self._max_retries,
                    budget_remaining,
                )
                await asyncio.sleep(delay)
                budget_remaining -= delay
                continue

            if response.status_code not in RETRY_STATUS_CODES or attempt == self._max_retries:
                return response

            delay = self._retry_after_delay(response, attempt, budget_remaining)
            if delay <= 0:
                return response
            logger.debug(
                "Retrying %s %s after HTTP %d (attempt %d/%d, budget %.1fs)",
                request.method,
                request.url.path,
                response.status_code,
                attempt + 1,
                self._max_retries,
                budget_remaining,
            )
            await asyncio.sleep(delay)
            budget_remaining -= delay

        return response  # pragma: no cover

    def _delay(self, attempt: int, budget: float) -> float:
        raw = _BASE_DELAY * (2**attempt) + random.uniform(0, 0.1)
        return min(raw, budget)

    def _retry_after_delay(
        self, response: httpx2.Response, attempt: int, budget: float
    ) -> float:
        header = response.headers.get("retry-after")
        if header:
            parsed = _parse_retry_after(header)
            if parsed is not None:
                return min(parsed, _RETRY_AFTER_MAX_WAIT, budget)
        return self._delay(attempt, budget)

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
    except Exception:
        return None
