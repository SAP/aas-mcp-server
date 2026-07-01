# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
HTTP client configuration for AAS MCP Server.

Authentication uses a custom httpx.AsyncAuth subclass (BearerTokenAuth) that
delegates to a BackendTokenProvider to obtain the token for every outbound
request. This supports multiple strategies:

- ForwardStrategy (default): reads the validated OAuth access token from
  FastMCP's request context via get_access_token() on every outbound request.
- TokenExchangeStrategy: performs RFC 8693 token exchange to obtain a
  backend-scoped token that preserves user identity.
- NoneStrategy: adds no Authorization header (public or mTLS backends).

For stdio transport (or when OAuth is not configured), ForwardStrategy returns
None and no Authorization header is added.
"""

import ipaddress
import logging
import math
import os
from typing import AsyncGenerator
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

from .backend_auth import BackendTokenProvider, ForwardStrategy
from .constants import (
    ENV_AAS_HTTP_TIMEOUT,
    DEFAULT_HTTP_TIMEOUT,
)

# HTTP headers
HEADER_ACCEPT = "Accept"
HEADER_AUTHORIZATION = "Authorization"
CONTENT_TYPE_JSON = "application/json"

# Authorization format
AUTH_BEARER_FORMAT = "Bearer {token}"

# Allowed URL schemes for AAS backend
_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Link-local ranges used by cloud metadata services.
# These are the only IPs that pose a genuine SSRF risk when present as a
# literal IP in AAS_BASE_URL — an operator would never intentionally target
# 169.254.169.254. All other private/RFC-1918 ranges (10/8, 172.16/12,
# 192.168/16) are legitimate Docker / on-premises backend addresses and are
# NOT blocked here. Network-level controls are the right enforcement layer
# for restricting what backends the server is allowed to reach in production.
_CLOUD_METADATA_NETWORKS = [
    ipaddress.ip_network("169.254.0.0/16"),  # AWS/GCP/Azure/DO metadata
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]


def _is_cloud_metadata_ip(ip_str: str) -> bool:
    """Return True if the IP is a cloud metadata / link-local address."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    # Unwrap IPv4-mapped IPv6 (::ffff:169.254.169.254)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        return _is_cloud_metadata_ip(str(addr.ipv4_mapped))
    return any(addr in net for net in _CLOUD_METADATA_NETWORKS)


def validate_backend_url(url: str) -> None:
    """
    Validate that AAS_BASE_URL is a safe HTTP/HTTPS URL.

    Scope of this check
    -------------------
    AAS_BASE_URL is operator-controlled configuration, not user input.
    The SSRF risk profile is therefore narrow:

    - Wrong scheme (file://, ftp://, ldap://) — operator error or env-var
      injection. Blocked: only http:// and https:// are permitted.
    - Cloud metadata literal IPs (169.254.0.0/16, fe80::/10) — an operator
      would never intentionally point AAS_BASE_URL at a metadata endpoint;
      its presence strongly indicates misconfiguration or injection. Blocked.

    What is NOT blocked
    -------------------
    - RFC 1918 private addresses (10/8, 172.16/12, 192.168/16): these are
      the standard Docker network ranges and are the most common backend
      addresses in containerised deployments. Blocking them would make the
      server unusable in any Docker/Compose/Kubernetes environment.
    - Hostnames that resolve to private IPs (e.g. Docker service names like
      'aas-env-rbac'): same reason. Docker service discovery relies on
      internal DNS that resolves to RFC 1918 addresses by design.

    Network-level egress controls (firewalls, Kubernetes NetworkPolicy,
    egress proxies) are the appropriate enforcement layer for restricting
    which backends the server is permitted to reach in production.

    Raises ValueError with an actionable message on any violation.
    """
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise ValueError(f"AAS_BASE_URL is not a valid URL: {url!r}") from exc

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"AAS_BASE_URL uses scheme {parsed.scheme!r}, which is not allowed. "
            f"Only 'http' and 'https' are permitted. "
            f"If you intended to point at your AAS backend, check the URL — "
            f"it should start with 'http://' or 'https://'."
        )

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(
            f"AAS_BASE_URL has no hostname: {url!r}. "
            f"Provide a full URL such as 'http://aas-backend:8081'."
        )

    # Only block literal cloud metadata IPs — not general private ranges.
    # Docker service hostnames and RFC 1918 IPs are legitimate backend targets.
    try:
        ip = ipaddress.ip_address(hostname)
        if _is_cloud_metadata_ip(str(ip)):
            raise ValueError(
                f"AAS_BASE_URL points to a cloud metadata IP address ({hostname}). "
                f"This address is reserved for cloud instance metadata services "
                f"(AWS/GCP/Azure/DigitalOcean) and cannot be an AAS backend. "
                f"If this was unintentional, check the AAS_BASE_URL value. "
                f"Expected format: 'http://your-aas-backend:8081'."
            )
    except ValueError as exc:
        if "AAS_BASE_URL" in str(exc):
            raise  # re-raise our own errors, not ipaddress parse errors


class BearerTokenAuth(httpx.Auth):
    """
    httpx.Auth implementation that obtains a bearer token via a
    BackendTokenProvider and injects it into every outbound AAS backend call.

    The provider is called at request time so each tool invocation uses the
    token appropriate for that specific MCP session / strategy.

    Overrides async_auth_flow (used by httpx.AsyncClient) to avoid bridging
    async/sync contexts — the server runs inside an asyncio event loop and
    calling run_until_complete() from within a running loop raises RuntimeError.

    Args:
        provider: Backend token provider. Defaults to ForwardStrategy (current
                  behaviour: forward upstream token from FastMCP context).
    """

    def __init__(self, provider: BackendTokenProvider | None = None) -> None:
        self._provider: BackendTokenProvider = provider if provider is not None else ForwardStrategy()

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        token_str = await self._provider.get_token()
        if token_str is not None:
            logger.debug(
                "Backend token obtained via %s: length=%d",
                type(self._provider).__name__,
                len(token_str),
            )
            request.headers[HEADER_AUTHORIZATION] = AUTH_BEARER_FORMAT.format(token=token_str)
        else:
            logger.debug(
                "No backend token from %s — no Authorization header added",
                type(self._provider).__name__,
            )
        yield request


def build_async_client(
    base_url: str,
    backend_token_provider: BackendTokenProvider | None = None,
) -> httpx.AsyncClient:
    """
    Build an async HTTP client configured with the given backend token strategy.

    Validates base_url to prevent SSRF attacks before creating the client.

    Args:
        base_url: Base URL for the AAS backend.
        backend_token_provider: Token provider for backend auth. Defaults to
                                 ForwardStrategy (forward upstream token as-is).

    Returns:
        Configured httpx.AsyncClient instance

    Raises:
        ValueError: If base_url fails security validation or AAS_HTTP_TIMEOUT
                    is not a valid positive number.
    """
    validate_backend_url(base_url)

    _raw_timeout = os.getenv(ENV_AAS_HTTP_TIMEOUT, str(DEFAULT_HTTP_TIMEOUT))
    try:
        timeout = float(_raw_timeout)
    except ValueError:
        raise ValueError(
            f"Invalid value for AAS_HTTP_TIMEOUT: {_raw_timeout!r} is not a number. "
            f"Provide a positive finite number in seconds (default: {DEFAULT_HTTP_TIMEOUT})."
        )
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError(
            f"Invalid value for AAS_HTTP_TIMEOUT: {timeout!r} is not allowed. "
            f"Value must be a positive finite number in seconds (default: {DEFAULT_HTTP_TIMEOUT})."
        )

    return httpx.AsyncClient(
        base_url=base_url,
        headers={HEADER_ACCEPT: CONTENT_TYPE_JSON},
        auth=BearerTokenAuth(provider=backend_token_provider),
        timeout=timeout,
        follow_redirects=False,  # Never follow redirects to prevent open-redirect SSRF
    )
