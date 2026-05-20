# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
HTTP client configuration for AAS MCP Server.

Authentication uses a custom httpx.Auth subclass (BearerTokenAuth) that reads
the validated OAuth access token from FastMCP's request context via
get_access_token() on every outbound request. This works correctly across all
FastMCP versions because it does not rely on get_http_headers(), which in
FastMCP >=3.3 explicitly excludes the Authorization header from forwarding.

For stdio transport (or when OAuth is not configured), get_access_token()
returns None and no Authorization header is added.
"""

import ipaddress
import os
import socket
from typing import Generator
from urllib.parse import urlparse

import httpx
from fastmcp.server.dependencies import get_access_token

from .constants import (
    ENV_AAS_HTTP_TIMEOUT,
    DEFAULT_HTTP_TIMEOUT,
    LOCALHOST_ADDRESSES,
)

# HTTP headers
HEADER_ACCEPT = "Accept"
HEADER_AUTHORIZATION = "Authorization"
CONTENT_TYPE_JSON = "application/json"

# Authorization format
AUTH_BEARER_FORMAT = "Bearer {token}"

# Allowed URL schemes for AAS backend
_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _is_ip_blocked(ip_str: str) -> bool:
    """
    Return True if the IP address is private, reserved, or otherwise unsafe.

    Uses ipaddress built-in traits rather than a manual CIDR denylist.
    This correctly handles all alternate representations:
    - Octal/hex literal forms (handled by ipaddress parser)
    - IPv4-mapped IPv6 (e.g. ::ffff:10.0.0.1) — unpacked and re-checked
    - Teredo / 6to4 embedded IPv4 — also re-checked

    An address is blocked if it is any of:
    - Loopback          (127.0.0.1, ::1)
    - Private           (10/8, 172.16/12, 192.168/16, fc00::/7)
    - Link-local        (169.254.0.0/16 — cloud metadata; fe80::/10)
    - Reserved          (240/4 and other IANA reserved ranges)
    - Unspecified       (0.0.0.0, ::)
    - Multicast
    - Carrier-grade NAT (100.64/10)
    """
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable → reject

    # Unwrap IPv4-mapped IPv6 (::ffff:10.0.0.1 → 10.0.0.1) and re-check
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        return _is_ip_blocked(str(addr.ipv4_mapped))

    # Carrier-grade NAT (100.64.0.0/10) — not covered by is_private
    if isinstance(addr, ipaddress.IPv4Address):
        if addr in ipaddress.ip_network("100.64.0.0/10"):
            return True

    return (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_unspecified
        or addr.is_multicast
    )


def validate_backend_url(url: str) -> None:
    """
    Validate that AAS_BASE_URL is a safe HTTP/HTTPS URL.

    Prevents SSRF attacks where a malicious or misconfigured AAS_BASE_URL
    could direct requests to cloud metadata endpoints (169.254.169.254),
    internal services, or non-HTTP schemes (file://, ftp://).

    Raises ValueError with a descriptive message on any violation.
    DNS resolution is intentionally NOT performed here — the backend URL is
    an operator-controlled value, and network-level controls (firewalls,
    egress proxies) are the appropriate enforcement layer for production.
    The check here guards against obvious misconfigurations and the most
    common SSRF patterns.
    """
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise ValueError(f"AAS_BASE_URL is not a valid URL: {url!r}") from exc

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"AAS_BASE_URL scheme {parsed.scheme!r} is not allowed. "
            f"Only 'http' and 'https' are permitted."
        )

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"AAS_BASE_URL has no hostname: {url!r}")

    # Explicitly allow localhost addresses for local development.
    # All other hostnames are checked against the blocked IP list.
    if hostname in LOCALHOST_ADDRESSES:
        return

    # If the hostname is already an IP address, validate it directly
    try:
        ip = ipaddress.ip_address(hostname)
        if _is_ip_blocked(str(ip)):
            raise ValueError(
                f"AAS_BASE_URL resolves to a private/reserved IP address "
                f"({hostname}). Cloud metadata endpoints and internal network "
                f"ranges are not permitted as backend targets."
            )
    except ValueError as e:
        # Re-raise our own errors
        if "AAS_BASE_URL" in str(e):
            raise
        # hostname is a domain name (not an IP) — check if it resolves to a blocked range.
        # Note: this is a best-effort check; it does not prevent DNS rebinding in production.
        # Use egress proxies / network policies for production SSRF prevention.
        try:
            resolved_ips = [
                info[4][0]
                for info in socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
            ]
            for ip_str in resolved_ips:
                if _is_ip_blocked(ip_str):
                    raise ValueError(
                        f"AAS_BASE_URL hostname {hostname!r} resolves to a "
                        f"private/reserved IP ({ip_str}). Cloud metadata endpoints "
                        f"and internal network ranges are not permitted."
                    )
        except OSError:
            # DNS resolution failed at startup — allow it; the backend
            # may not be reachable at config time (Docker network, etc.)
            pass


class BearerTokenAuth(httpx.Auth):
    """
    httpx.Auth implementation that injects the current request's OAuth Bearer
    token into every outbound AAS backend call.

    Reads the token from FastMCP's get_access_token() at request time, so each
    tool invocation uses the token belonging to that specific MCP session user.
    Returns no Authorization header on stdio transport or when OAuth is not
    configured (get_access_token() returns None in those cases).
    """

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        access_token = get_access_token()
        if access_token is not None:
            request.headers[HEADER_AUTHORIZATION] = AUTH_BEARER_FORMAT.format(
                token=access_token.token
            )
        yield request


def build_async_client(base_url: str) -> httpx.AsyncClient:
    """
    Build an async HTTP client that forwards the OAuth Bearer token
    per-request via BearerTokenAuth.

    Validates base_url to prevent SSRF attacks before creating the client.

    Args:
        base_url: Base URL for the AAS backend

    Returns:
        Configured httpx.AsyncClient instance

    Raises:
        ValueError: If base_url fails security validation
    """
    validate_backend_url(base_url)
    timeout = float(os.getenv(ENV_AAS_HTTP_TIMEOUT, str(DEFAULT_HTTP_TIMEOUT)))
    return httpx.AsyncClient(
        base_url=base_url,
        headers={HEADER_ACCEPT: CONTENT_TYPE_JSON},
        auth=BearerTokenAuth(),
        timeout=timeout,
        follow_redirects=False,  # Never follow redirects to prevent open-redirect SSRF
    )
