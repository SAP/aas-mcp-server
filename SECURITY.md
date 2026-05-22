# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Report vulnerabilities privately via the [GitHub Security Advisory](https://github.com/SAP/aas-mcp-server/security/advisories/new) mechanism, or by emailing [ospo@sap.com](mailto:ospo@sap.com).

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested mitigation (if any)

You will receive an acknowledgement within **5 business days** and a resolution timeline within **14 business days**.

## Security Design

### Authentication & Authorization

- OAuth 2.1 + PKCE is enforced on HTTP transports when `OAUTH_ISSUER_URL` is set
- Tokens are validated on every request (signature, issuer, expiry, audience)
- The `stdio` transport bypasses inbound auth by design — it is a local process model where OS-level isolation provides security
- `OAUTH_AUDIENCE` should always be set in production to prevent token passthrough to unintended resource servers

### Token Forwarding

The server forwards the validated user Bearer token to the AAS backend. This is only safe when:
1. `OAUTH_AUDIENCE` is configured to validate that the token was issued for the correct resource server
2. The AAS backend and MCP server share the same OAuth provider

### Backend URL Validation

`AAS_BASE_URL` is validated at startup to reject non-HTTP schemes (`file://`, `ftp://`) and requests to private IP ranges (`169.254.x.x` cloud metadata, `10.x.x.x`, `192.168.x.x`, etc.). This mitigates SSRF attacks from misconfigured deployments.

### Error Information

`mask_error_details=True` is set on the FastMCP server to prevent internal backend error messages, AAS backend URLs, and internal hostnames from leaking to MCP clients.

### Rate Limiting

The server applies per-client rate limiting (default: 60 requests/minute, configurable via `MCP_RATE_LIMIT_PER_MINUTE`) to mitigate abuse of valid tokens.

## Known Limitations

- **No production SSRF prevention for `AAS_BASE_URL` DNS rebinding**: The startup URL check does a best-effort DNS resolution, but DNS-based rebinding attacks in production require network-level controls (egress proxies, firewall rules). Operators should enforce outbound network policies.
- **`OAUTH_AUDIENCE` is optional**: Omitting it allows any token from the configured issuer to be accepted. A startup warning is emitted. Set it in all production deployments.
- **`stdio` transport has no inbound auth**: By design. Do not expose a `stdio` server over a network socket.
