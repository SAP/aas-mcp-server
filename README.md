# AAS MCP Server

> OpenAPI-to-MCP bridge for Asset Administration Shell (AAS) APIs

Converts OpenAPI specifications into Model Context Protocol (MCP) tools, enabling LLMs to interact with AAS services.

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

## Quick Start

### Prerequisites

1. **AAS OpenAPI Specifications** - [Download from GitHub](https://github.com/admin-shell-io/aas-specs)
2. **AAS Backend Server** - Eclipse BaSyx, FA³ST Service, SAP BNAC, etc.
3. **Python 3.12+** OR **Docker**

### Setup

1. **Get AAS Specifications**:
   ```bash
   mkdir specs && cd specs
   # Download from https://github.com/admin-shell-io/aas-specs/tree/main/schemas/openapi
   ```

2. **Create config.yaml** (copy from config.yaml.template):
   ```yaml
   components:
     aas-repo:
       official_spec: specs/AssetAdministrationShellRepositoryServiceSpecification-V3.1.1_SSP-001.yaml
       curation:
         allowlist:
           - [get, "*"]  # All GET operations (wildcard)
           - [post, /shells]
   ```

3. **Run**:
   ```bash
   # Docker (recommended)
   docker run \
     -v $(pwd)/config.yaml:/app/config/config.yaml \
     -v $(pwd)/specs:/app/specs \
     -e AAS_COMPONENT=aas-repo \
     -e AAS_BASE_URL=http://your-backend:8080 \
     -i aas-mcp-server

   # Or install locally
   pip install -e .
   aas-mcp-server --component aas-repo --base-url http://localhost:8080 --config config.yaml
   ```

## Configuration

### Basic (Official Spec Only)

```yaml
components:
  aas-repo:
    official_spec: specs/aas-repo-spec.yaml
```

### Filtered (Implementation-Specific)

Filter to only endpoints your backend supports:

```yaml
components:
  aas-repo:
    official_spec: specs/aas-repo-official.yaml
    implementation_spec: specs/basyx-supported-endpoints.yaml
```

Result: Only endpoints in **both** specs are exposed (intersection).

### With Curation (Wildcards Supported)

Control which operations are exposed using wildcards:

```yaml
components:
  aas-repo:
    official_spec: specs/aas-repo-spec.yaml
    curation:
      allowlist:
        # Specific operations
        - [get, /shells]
        - [post, /shells]
        
        # Wildcards
        - [get, "*"]          # All GET operations on any path
        - ["*", /shells]      # All methods on /shells path
        - ["*", "*"]          # All methods on all paths (use with caution!)
        
      aliases:
        GetAllAssetAdministrationShells: list_shells
        PostAssetAdministrationShell: create_shell
```

See [config.yaml.template](config.yaml.template) for complete options.

## MCP Client Configuration

The same `aas-mcp-server` binary works with all MCP-compatible clients — the server
logic is identical, only the config format differs per client. Full examples for all
clients are available in [client_config_examples.txt](client_config_examples.txt).

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
or `%APPDATA%\Claude\claude_desktop_config.json` (Windows).
See [claude_desktop_config.example.json](claude_desktop_config.example.json) for
the full four-component example.

```json
{
  "mcpServers": {
    "aas-repo": {
      "command": "aas-mcp-server",
      "args": [
        "--component", "aas-repo",
        "--base-url", "http://localhost:8080",
        "--config", "/path/to/your/config.yaml"
      ],
      "env": { "LOG_LEVEL": "INFO" }
    }
  }
}
```

### Claude CLI (Claude Code)

```bash
claude mcp add aas-repo \
  --env LOG_LEVEL=INFO \
  -- aas-mcp-server \
     --component aas-repo \
     --base-url http://localhost:8080 \
     --config /path/to/your/config.yaml
```

Scope options: `--scope local` (default, current project), `--scope user` (all projects),
`--scope project` (shared with team via `.mcp.json`).

### OpenCode

Add to `opencode.json` in your project root:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "aas-repo": {
      "type": "local",
      "command": [
        "aas-mcp-server",
        "--component", "aas-repo",
        "--base-url", "http://localhost:8080",
        "--config", "/path/to/your/config.yaml"
      ],
      "enabled": true,
      "environment": { "LOG_LEVEL": "INFO" }
    }
  }
}
```

See [client_config_examples.txt](client_config_examples.txt) for all four components,
authentication setup, and write-mode configuration for every client.

## Docker Usage

### Basic (stdio — local use, no auth)

```bash
docker run \
  -v $(pwd)/config.yaml:/app/config/config.yaml \
  -v $(pwd)/specs:/app/specs \
  -e AAS_COMPONENT=aas-repo \
  -e AAS_BASE_URL=http://your-backend:8080 \
  -i aas-mcp-server
```

### HTTP Transport with OAuth 2.1

For remote deployments where MCP clients connect over the network:

```bash
docker run \
  --network your-docker-network \
  -v $(pwd)/config.yaml:/app/config/config.yaml \
  -v $(pwd)/specs:/app/specs \
  -e AAS_COMPONENT=aas-repo \
  -e AAS_BASE_URL=http://your-backend:8080 \
  -e MCP_TRANSPORT=streamable-http \
  -e MCP_HOST=0.0.0.0 \
  -e MCP_PORT=8000 \
  -e OAUTH_ISSUER_URL=https://your-idp/realms/your-realm \
  -e OAUTH_JWKS_URI=https://your-idp/realms/your-realm/protocol/openid-connect/certs \
  -e OAUTH_SERVER_BASE_URL=http://localhost:8000 \
  -p 8000:8000 \
  aas-mcp-server
```

Register with an MCP client (example using Claude CLI):

```bash
claude mcp add aas-repo \
  --transport http \
  --scope user \
  --client-id your-oauth-client-id \
  http://localhost:8000/mcp
```

### Custom Config Path

```bash
docker run \
  -v $(pwd)/my-config.yaml:/custom/config.yaml \
  -v $(pwd)/specs:/app/specs \
  -e CONFIG_PATH=/custom/config.yaml \
  -e AAS_COMPONENT=aas-repo \
  -e AAS_BASE_URL=http://your-backend:8080 \
  -i aas-mcp-server
```

## OAuth 2.1 Authorization

The server supports OAuth 2.1 + PKCE for HTTP transports. When enabled, the
server validates inbound Bearer tokens and forwards them to the AAS backend.

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `OAUTH_ISSUER_URL` | Yes (to enable) | OAuth provider issuer URL. Auth is disabled when not set. |
| `OAUTH_JWKS_URI` | Recommended | JWKS endpoint. Defaults to `{OAUTH_ISSUER_URL}/.well-known/jwks.json` — override for Keycloak and other non-standard providers. |
| `OAUTH_SERVER_BASE_URL` | Required for Docker | Public URL of the MCP server as seen by clients. Must match the URL the MCP client was registered with. Avoids `0.0.0.0` appearing in resource metadata. |
| `OAUTH_AUDIENCE` | Recommended | Expected `aud` claim. If unset, audience validation is skipped (warning logged). |
| `OAUTH_REQUIRED_SCOPES` | Optional | Comma-separated required scopes, e.g. `aas:read,aas:write`. |
| `MCP_RATE_LIMIT_PER_MINUTE` | Optional | Max requests per client per minute. Default: 60. |

### Token forwarding

The validated Bearer token is automatically forwarded to the AAS backend on
every outbound request via a per-request `httpx.Auth` implementation. No
separate backend credentials are needed — the same OAuth provider can protect
both the MCP server and the AAS backend.

> **FastMCP version note:** Token forwarding uses `get_access_token()` from
> FastMCP's request context. If you build a custom Docker image that upgrades
> FastMCP, pin to a tested version in `pyproject.toml`. FastMCP ≥3.3 changed
> `get_http_headers()` to exclude `authorization` — any implementation relying
> on that for token forwarding will silently break. The `BearerTokenAuth` class
> in this server is not affected.

### Provider JWKS paths

Different providers use different JWKS paths. Always set `OAUTH_JWKS_URI`
explicitly rather than relying on the default:

| Provider | `OAUTH_JWKS_URI` |
|---|---|
| Keycloak | `{issuer}/protocol/openid-connect/certs` |
| Azure AD | `https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys` |
| Auth0 | `https://{domain}/.well-known/jwks.json` |
| SAP IAS | `https://{tenant}.accounts.ondemand.com/oauth2/certs` |

## Supported Components

- `aas-repo` - Asset Administration Shell Repository
- `submodel-repo` - Submodel Repository  
- `aas-registry` - AAS Registry
- `submodel-registry` - Submodel Registry

## Testing

Run tests:
```bash
# Unit tests only
tests/run_tests.sh

# With integration tests (requires backend on port 8081)
tests/run_tests.sh --integration
```

## Security

- **Read-only by default** - Write operations disabled unless `--enable-writes`
- **Allowlist-based** - Only explicitly allowed operations exposed
- **Wildcard patterns** - `[get, "*"]`, `["*", /path]`, `["*", "*"]`
- **Pagination limits** - Max 100 items per request

## How It Works

When the server starts, it processes the OpenAPI specification through a pipeline before handing it to FastMCP:

1. **Load** — reads the spec file and applies any overlay (rename, add descriptions, etc.)
2. **Flatten** — resolves `$ref` inheritance chains and merges `allOf` compositions into flat schemas. This is necessary because the official IDTA AAS spec uses multi-level `allOf` + `$ref` inheritance (e.g. `AssetAdministrationShell` → `Identifiable` → `Referable`). Without flattening, FastMCP only sees the properties defined directly on the schema and misses all inherited fields like `id`, `modelType`, and `assetInformation`. Circular references are handled by keeping a `$ref` pointer at the cycle point instead of recursing infinitely.
3. **Curate** — applies the allowlist to filter paths, enforces read-only mode, applies operation ID aliases, and caps pagination limits.
4. **Prune** — removes `components/schemas` entries that are no longer reachable from any remaining path. This prevents FastMCP's schema validator from processing circular schemas that belonged to paths filtered out in the previous step, which would otherwise cause it to hang.
5. **Generate** — FastMCP generates MCP tools from the processed spec and wires them to the HTTP client.

> **Note on `allOf` merging:** When multiple `allOf` elements define the same non-property keyword (e.g. `description`, `additionalProperties`), the first value is kept. This is safe for the standard IDTA AAS spec but may produce weaker validation constraints on specs with conflicting allOf-level keywords.

## Troubleshooting

### "Configuration file not found"

**Provide config via**:
- `--config /path/to/config.yaml`
- `CONFIG_PATH` environment variable
- Default: `/app/config/config.yaml`

### "official_spec file not found"

**Check**:
- Paths in config.yaml are correct
- Specs are mounted (Docker): `-v $(pwd)/specs:/app/specs`

### OAuth / HTTP Transport

#### "Got new credentials, but server rejected them on reconnect"

Token validation is failing inside the container. Check the container logs:

```bash
docker logs <container-id> 2>&1 | grep -E "Token validation|JWKS|401|ERROR"
```

**Common causes:**

**1. Wrong JWKS path (most common with Keycloak)**

The default JWKS path `/.well-known/jwks.json` is not standard — many providers
use a different path. Always set `OAUTH_JWKS_URI` explicitly:

```bash
# Keycloak
-e OAUTH_JWKS_URI=http://keycloak-host/realms/your-realm/protocol/openid-connect/certs

# Verify the correct path from your provider's discovery document:
curl -s https://your-idp/.well-known/openid-configuration | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['jwks_uri'])"
```

**2. Hostname not resolvable inside the Docker container**

Your IdP hostname (e.g. `keycloak.example.localhost`) may resolve on your host
machine but not inside the Docker container. Verify:

```bash
docker exec <container-id> python3 -c \
  "import socket; print(socket.gethostbyname('your-idp-hostname'))"
```

If it fails, add the hostname with `--add-host`:

```bash
# Find the IP your IdP resolves to on the host
python3 -c "import socket; print(socket.gethostbyname('your-idp-hostname'))"

# Add it to the container
docker run --add-host your-idp-hostname:<ip> ...
```

If your setup uses an nginx reverse proxy container, use the **proxy** container's
IP — not the IdP container's IP directly. The proxy listens on port 80 and routes
by hostname; the IdP container typically only listens on a high port (e.g. 8080)
and does not accept plain-hostname requests on port 80.

```bash
# Find all container names and IPs on your network
docker network inspect your-network | python3 -c "
import sys, json
data = json.load(sys.stdin)
for c in data[0].get('Containers', {}).values():
    print(c['Name'], c.get('IPv4Address'))
"
# Use the proxy container's IP (e.g. nginx-proxy), not the IdP container's IP

docker run --add-host your-idp-hostname:<proxy-ip> ...
```

To verify the hostname resolves AND reaches the JWKS endpoint from inside the container:

```bash
docker exec <container-id> python3 -c "
import urllib.request
resp = urllib.request.urlopen('http://your-idp-hostname/realms/your-realm/protocol/openid-connect/certs', timeout=5)
print('JWKS status:', resp.status)
"
```

**3. `resource` URL mismatch (`0.0.0.0` vs `localhost`)**

When `MCP_HOST=0.0.0.0`, the server's protected resource metadata advertises
`http://0.0.0.0:8000/mcp` as its URL, which doesn't match `http://localhost:8000/mcp`
that the MCP client registered. Set `OAUTH_SERVER_BASE_URL` to the public-facing URL:

```bash
-e OAUTH_SERVER_BASE_URL=http://localhost:8000
```

Verify the metadata is correct before registering with your MCP client:

```bash
curl -s http://localhost:8000/.well-known/oauth-protected-resource/mcp \
  | python3 -m json.tool
# "resource" must exactly match the URL you pass to your MCP client
```

**4. Wrong Docker network**

The container must be on the same network as your AAS backend and IdP:

```bash
# List container networks
docker ps --format "{{.Names}}\t{{.Networks}}"

# Use the correct network
docker run --network correct-network-name ...
```

#### "Not Found" when browser opens for authentication

The MCP client constructed the authorization URL using the wrong endpoint. This
happens when the server's `/.well-known/oauth-authorization-server` returns 404
(expected — this server is a pure resource server) and the client falls back
incorrectly. Ensure `--client-id` is passed when registering the server
(example using Claude CLI):

```bash
claude mcp add aas-repo \
  --transport http \
  --scope user \
  --client-id your-oauth-client-id \
  http://localhost:8000/mcp
```

#### MCP tool succeeds but AAS backend returns 401

The MCP server accepted the token but the backend rejected it. This is a
different failure from the MCP server itself returning 401.

**Symptom:** An MCP tool call returns something like:
```
Error calling tool 'list_shells': HTTP error 401:
```

**Check the MCP server logs for the outbound request:**

```bash
docker logs <container-id> 2>&1 | grep -A3 "send_request_headers\|aas-env\|GET /shells"
```

Look at the `headers` line. If `authorization` is absent, token forwarding
is not working.

**Common causes:**

**a. FastMCP version changed `get_http_headers()` behaviour**

FastMCP ≥3.3 explicitly excludes `authorization` from `get_http_headers()`.
The server uses `BearerTokenAuth` (a custom `httpx.Auth` class) to work around
this. If you see the header missing, verify you are running the current image:

```bash
docker exec <container-id> python3 -c "
from aas_mcp_server.http_client import BearerTokenAuth
print('BearerTokenAuth present — token forwarding is correct')
"
```

**b. Spring Security `issuer-uri` mismatch**

Spring Security validates the `iss` claim in the token with exact string
matching. If the MCP server was configured with
`OAUTH_ISSUER_URL=http://keycloak.basyx.localhost/realms/BaSyx` but the AAS
backend has `issuer-uri: http://keycloak:8080/realms/BaSyx`, Spring rejects
the token even though it is from the same Keycloak.

Decode the token to check the `iss` claim:

```bash
TOKEN=<your-token>
python3 -c "
import base64, json
payload = '$TOKEN'.split('.')[1]
payload += '=' * (4 - len(payload) % 4)
print('iss:', json.loads(base64.urlsafe_b64decode(payload)).get('iss'))
"
```

The `iss` value must exactly match the `issuer-uri` in the AAS backend's
Spring Security config. Set `OAUTH_ISSUER_URL` to whichever value the AAS
backend expects.

#### Manually testing the full token chain

To reproduce and isolate failures before involving an MCP client:

```bash
# 1. Get a token (replace with your provider's token endpoint)
TOKEN=$(curl -s -X POST \
  "https://your-idp/realms/your-realm/protocol/openid-connect/token" \
  -d "grant_type=password&client_id=your-client&username=user&password=pass&scope=openid" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2. Decode the token claims
python3 -c "
import base64, json
payload = '$TOKEN'.split('.')[1]
payload += '=' * (4 - len(payload) % 4)
c = json.loads(base64.urlsafe_b64decode(payload))
print('iss:', c.get('iss'))
print('aud:', c.get('aud'))
print('scope:', c.get('scope'))
"

# 3. Call the MCP server — should return 200
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1"}},"id":1}'
```

## License

Apache License 2.0 - See [LICENSE](LICENSE)
