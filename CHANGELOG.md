# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0](https://github.com/SAP/aas-mcp-server/compare/v0.1.0...v0.1.0) (2026-07-29)


### Documentation

* fix misleading PyPI partial-upload recovery advice ([47ed624](https://github.com/SAP/aas-mcp-server/commit/47ed624adde1d17be4e167ec396989f42459c962))
* mark PyPI publishing enabled and add release checklist notes ([e6875ad](https://github.com/SAP/aas-mcp-server/commit/e6875adf03b0cddc925961456d5eebef7ec75fc9))

## [0.1.0](https://github.com/SAP/aas-mcp-server/compare/v0.1.0...v0.1.0) (2026-07-29)


### Documentation

* fix misleading PyPI partial-upload recovery advice ([47ed624](https://github.com/SAP/aas-mcp-server/commit/47ed624adde1d17be4e167ec396989f42459c962))
* mark PyPI publishing enabled and add release checklist notes ([e6875ad](https://github.com/SAP/aas-mcp-server/commit/e6875adf03b0cddc925961456d5eebef7ec75fc9))

## [0.1.0](https://github.com/SAP/aas-mcp-server/compare/v0.1.0...v0.1.0) (2026-07-29)


### Features

* **release:** add deferred PyPI trusted-publish job (SAP OSPO spec, disabled) ([9c7ff14](https://github.com/SAP/aas-mcp-server/commit/9c7ff145a0071903e728f34d469758b6e23c7afe))
* **release:** add release-please job as release spine ([feb0baa](https://github.com/SAP/aas-mcp-server/commit/feb0baa3c9662947638e027886c8b18879a1ed6d))
* **release:** publish multi-arch image to GHCR with SBOM + attestation ([f9b8853](https://github.com/SAP/aas-mcp-server/commit/f9b885306cd92c9f3ba419b184618ad6c674272a))


### Bug Fixes

* **ci:** align lint job Python version to 3.12 ([fe87f80](https://github.com/SAP/aas-mcp-server/commit/fe87f802dd3ddf6583fd80a6d541c4f3285db3f7))


### Documentation

* **changelog:** revert to Unreleased so release-please authors the first changelog ([4839744](https://github.com/SAP/aas-mcp-server/commit/4839744ab78ea535e67b637d175b64aca94844d7))
* **release:** correct manual dispatch flow, lowercase GHCR ref, GITHUB_TOKEN CI note ([e6037b9](https://github.com/SAP/aas-mcp-server/commit/e6037b95286fca5201247eb396b5bb23937b2eb7))
* **release:** document SAP OSPO GHCR + PyPI onboarding prerequisites ([2059f82](https://github.com/SAP/aas-mcp-server/commit/2059f820ad769794dab4fa72a6234d8bda2547a4))

## [Unreleased]

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
