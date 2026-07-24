# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0]

### Added
- OAuth 2.1 + PKCE inbound authorization for HTTP transports using FastMCP's `JWTVerifier` and `RemoteAuthProvider`
- Token forwarding: validated Bearer token forwarded to AAS backend per-request via `BearerTokenAuth` (custom `httpx.Auth`)
- `OAUTH_SERVER_BASE_URL` env var to correctly advertise public server URL in RFC 9728 protected resource metadata
- RFC 9728 protected resource metadata endpoint (`/.well-known/oauth-protected-resource/mcp`) for MCP client discovery
- Rate limiting middleware (default 60 req/min, configurable via `MCP_RATE_LIMIT_PER_MINUTE`)
- SSRF protection: `AAS_BASE_URL` validated at startup to reject private IP ranges and non-HTTP schemes
- Non-root Docker container user (`appuser`, UID 1000)
- `mask_error_details=True` to prevent internal error leakage to MCP clients
- `SECURITY.md` with vulnerability reporting process and security design documentation
- JWKS well-known path support with `OAUTH_JWKS_URI` override for non-standard providers
- Startup warnings for missing `OAUTH_AUDIENCE` (token passthrough risk) and plain HTTP with OAuth enabled
- OpenAPI-to-MCP bridge for AAS (Asset Administration Shell) API services
- Support for four AAS component types: `aas-repo`, `submodel-repo`, `aas-registry`, `submodel-registry`
- Configurable tool allowlist with wildcard support (`[get, "*"]`, `["*", /path]`)
- Operation ID aliasing for better LLM tool naming
- Schema flattening for IDTA AAS `allOf`/`$ref` inheritance chains
- Pagination limit enforcement (max 100 items)
- Optional OpenAPI overlay support for customizing operation descriptions
- Docker image with `stdio` transport as default
- Support for `stdio`, `http`, `sse`, and `streamable-http` MCP transports

### Changed
- Removed static `AAS_TOKEN` / `AAS_API_KEY` credential support — OAuth Bearer token is the only authentication mechanism for HTTP transport
- `build_mcp_server()` now accepts `host` and `port` parameters for correct base URL construction
- Schema flattening now handles `allOf` compositions and `$ref` chains before FastMCP tool generation

### Security
- Addressed SSRF risk in backend URL configuration (CWE-918)
- Addressed information leakage via tool error messages (CWE-209)
- Addressed privilege escalation risk in Docker (container now runs as non-root)
- Addressed token passthrough risk (audience validation warning + documentation)
