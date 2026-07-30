# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0](https://github.com/SAP/aas-mcp-server/releases/tag/v0.1.0) (2026-07-29)

First public release of `aas-mcp-server` — an OpenAPI-to-MCP bridge that exposes Asset Administration Shell (AAS) APIs as Model Context Protocol tools so LLM agents can interact with any AAS-compliant backend.

### Added

**AAS + MCP core**
- OpenAPI-to-MCP bridge for AAS (Asset Administration Shell) API services
- Support for four AAS component types: `aas-repo`, `submodel-repo`, `aas-registry`, `submodel-registry`
- Configurable tool allowlist with wildcard support (`[get, "*"]`, `["*", /path]`, `["*", "*"]`)
- Operation ID aliasing for better LLM tool naming
- Schema flattening for IDTA AAS `allOf` / `$ref` inheritance chains (with cycle handling)
- Pagination limit enforcement (max 100 items per request)
- Optional OpenAPI overlay support for customizing operation descriptions
- Docker image with `stdio` transport as default
- Support for `stdio`, `http`, `sse`, and `streamable-http` MCP transports

**Authentication & authorization**
- OAuth 2.1 + PKCE inbound authorization for HTTP transports via FastMCP's `OIDCProxy`
- Bearer-token forwarding: validated inbound token forwarded to the AAS backend per-request via a custom `httpx.Auth` (`BearerTokenAuth`)
- RFC 9728 protected-resource metadata endpoint (`/.well-known/oauth-protected-resource/mcp`) for MCP client discovery
- `OAUTH_SERVER_BASE_URL` env var to correctly advertise the public server URL in protected-resource metadata
- JWKS well-known path support with `OAUTH_JWKS_URI` override for non-standard providers
- Startup warnings for missing `OAUTH_AUDIENCE` (token passthrough risk) and plain HTTP with OAuth enabled

**Hardening**
- Rate-limiting middleware (default 60 req/min, configurable via `MCP_RATE_LIMIT_PER_MINUTE`)
- SSRF protection: `AAS_BASE_URL` validated at startup to reject private IP ranges and non-HTTP schemes
- Non-root Docker container user (`appuser`, UID 1000)
- `mask_error_details=True` to prevent internal error leakage to MCP clients
- `SECURITY.md` with vulnerability reporting process and security design documentation

**Release infrastructure**
- Manual `workflow_dispatch` release flow driven by `release-please` (opens Release PR → merge → tag + GitHub Release) ([feb0baa](https://github.com/SAP/aas-mcp-server/commit/feb0baa3c9662947638e027886c8b18879a1ed6d))
- Multi-arch (`linux/amd64`, `linux/arm64`) GHCR publish with SBOM (`sbom.spdx.json`) and build-provenance attestation ([f9b8853](https://github.com/SAP/aas-mcp-server/commit/f9b885306cd92c9f3ba419b184618ad6c674272a))
- PyPI publishing via OIDC Trusted Publishing (SAP central account, no stored token) ([9c7ff14](https://github.com/SAP/aas-mcp-server/commit/9c7ff145a0071903e728f34d469758b6e23c7afe))
- All GitHub Actions pinned to commit SHAs for supply-chain integrity
- CI matrix for Python 3.12 / 3.13 / 3.14 with pytest, ruff, mypy, and a Docker smoke test

### Changed

- Removed static `AAS_TOKEN` / `AAS_API_KEY` credential support — OAuth Bearer token is the only authentication mechanism for HTTP transport
- `build_mcp_server()` now accepts `host` and `port` parameters for correct base URL construction
- Schema flattening now handles `allOf` compositions and `$ref` chains before FastMCP tool generation

### Fixed

- **ci:** align lint job Python version to 3.12 ([fe87f80](https://github.com/SAP/aas-mcp-server/commit/fe87f802dd3ddf6583fd80a6d541c4f3285db3f7))

### Security

- Addressed SSRF risk in backend URL configuration (CWE-918)
- Addressed information leakage via tool error messages (CWE-209)
- Addressed privilege escalation risk in Docker (container now runs as non-root)
- Addressed token passthrough risk (audience validation warning + documentation)

### Documentation

- Comprehensive `README.md` covering configuration, MCP client examples (Claude Desktop, Claude CLI, OpenCode), Docker usage, OAuth setup, and troubleshooting
- `RELEASE.md` covering the release process, SAP OSPO onboarding (GHCR + PyPI), the two-run dispatch flow, and PyPI publish troubleshooting ([2059f82](https://github.com/SAP/aas-mcp-server/commit/2059f820ad769794dab4fa72a6234d8bda2547a4), [e6037b9](https://github.com/SAP/aas-mcp-server/commit/e6037b95286fca5201247eb396b5bb23937b2eb7), [e6875ad](https://github.com/SAP/aas-mcp-server/commit/e6875adf03b0cddc925961456d5eebef7ec75fc9), [47ed624](https://github.com/SAP/aas-mcp-server/commit/47ed624adde1d17be4e167ec396989f42459c962))
- `SECURITY.md` with disclosure policy and security design notes
- Config template (`config.yaml.template`) and MCP client config examples (`client_config_examples.txt`)

### Notes

- **No static credentials.** `AAS_TOKEN` / `AAS_API_KEY` are not supported; OAuth Bearer token is the only auth mechanism for HTTP transport.
- **Schema flattening** happens before FastMCP tool generation — necessary because the official IDTA AAS spec uses multi-level `allOf` + `$ref` inheritance that FastMCP does not resolve on its own.
- **First release, no upgrade path.**

Full commit history: <https://github.com/SAP/aas-mcp-server/commits/v0.1.0>
