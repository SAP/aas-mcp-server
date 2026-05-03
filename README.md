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

### Basic

```bash
docker run \
  -v $(pwd)/config.yaml:/app/config/config.yaml \
  -v $(pwd)/specs:/app/specs \
  -e AAS_COMPONENT=aas-repo \
  -e AAS_BASE_URL=http://your-backend:8080 \
  -i aas-mcp-server
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

## License

Apache License 2.0 - See [LICENSE](LICENSE)
