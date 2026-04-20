# AAS MCP Server

**OpenAPI-to-MCP adapter for Asset Administration Shell (AAS) APIs.**

This MCP server acts as a bridge between LLMs and your AAS backend server. It converts OpenAPI specifications into MCP tools, enabling LLMs to interact with AAS services through a safe, curated interface.

**Pure Adapter Pattern**: This server doesn't bundle any AAS backend implementation. You provide your own AAS backend (SAP BNAC AAS Server, Eclipse BaSyx, FA³ST Service, or custom), and this server translates LLM requests into HTTP calls to your backend.

## Supported Components

- **AAS Repository** - Manage Asset Administration Shells
- **Submodel Repository** - Manage Submodels
- **AAS Registry** - Discover and register AAS components
- **Submodel Registry** - Discover and register Submodels

## Prerequisites

You need an AAS backend server running. Options:

1. **Production**: Use your existing SAP BNAC AAS Server, Eclipse BaSyx, FA³ST Service, or custom AAS server
2. **Development/Testing**: Start a reference backend with Docker Compose (see below)

## Install

```bash
pip install aas-mcp-server
```

## Quick Start

### With Existing AAS Backend

Point the MCP server to your backend URL:

```bash
# AAS Repository
aas-mcp-server --component aas-repo --base-url http://your-backend:8080

# Submodel Repository
aas-mcp-server --component submodel-repo --base-url http://your-backend:8081

# AAS Registry
aas-mcp-server --component aas-registry --base-url http://your-backend:8083

# Submodel Registry
aas-mcp-server --component submodel-registry --base-url http://your-backend:8084
```

### For Testing/Development

Start a reference backend with Docker Compose:

```bash
# Start reference backend
docker-compose up -d

# Connect MCP server to it
aas-mcp-server --component aas-repo --base-url http://localhost:8080
```

## OpenAPI Specifications

**By default**, the server uses the **official AAS OpenAPI specifications** (V3.1.1 SSP-001):
- Full, unfiltered specs from IDTA/AAS standards
- Located in `openapi/` directory
- Works with any AAS-compliant backend

**Example derived specs included**:
- `openapi/derived/` contains pre-generated example specs
- These are filtered to match specific implementation capabilities
- Use these as examples for creating your own derived specs

### Using Different Specifications

**Option 1: Use Default (Official AAS Specs)**
```bash
# No additional flags needed - uses official specs by default
aas-mcp-server --component aas-repo --base-url http://your-backend:8080
```

**Option 2: Use Example Derived Specs**
```bash
# Use pre-generated example spec
aas-mcp-server \
  --component aas-repo \
  --base-url http://your-backend:8080 \
  --openapi openapi/derived/AssetAdministrationShellRepositoryServiceSpecification-V3.1.1_SSP-001-resolved-derived.yaml
```

**Option 3: Generate Your Own Derived Specs**

If your backend doesn't implement all official AAS endpoints, generate a filtered spec:

1. **Document your implementation's endpoints**
   ```bash
   # Create docs/your-impl-endpoints.json with your supported endpoints
   # See docs/ directory for example endpoint documentation files
   ```

2. **Create configuration**
   ```bash
   cp configs/config.yaml.template configs/my-impl-config.yaml
   # Edit to point to your implementation docs
   ```

3. **Generate derived specs**
   ```bash
   python3 scripts/generate_implementation.py --config configs/my-impl-config.yaml
   ```

4. **Use your generated spec**
   ```bash
   aas-mcp-server \
     --component aas-repo \
     --base-url http://your-backend:8080 \
     --openapi openapi/derived/your-derived-spec.yaml
   ```

See `configs/README.md` for detailed instructions.

## Configuration

### Command-line Arguments

- `--component` (required): Which AAS component to serve
- `--base-url` (required): URL of your AAS backend server
- `--openapi`: Custom OpenAPI spec path (default: official AAS spec for component)
- `--config`: Path to implementation config file (for loading curation settings)
- `--enable-writes`: Enable write operations (default: read-only)
- `--log-level`: Logging level (default: INFO)
- `--transport`: Transport protocol (default: stdio)

### Environment Variables

- `AAS_BASE_URL`: Override the default base URL
- `AAS_OPENAPI_PATH`: Override the default OpenAPI spec path
- `AAS_MCP_ENABLE_WRITES`: Set to "1" to enable write operations
- `LOG_LEVEL`: Set logging level
- `MCP_TRANSPORT`: Set transport protocol

### Example: Enable Writes
```bash
aas-mcp-server --component aas-repo --base-url http://localhost:8080 --enable-writes
```

### Example: Custom OpenAPI Spec
```bash
aas-mcp-server \
  --component submodel-repo \
  --base-url http://localhost:8081 \
  --openapi ./my-custom-spec.yaml
```

## Claude Desktop Configuration

Add each component separately to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "aas-repo": {
      "command": "aas-mcp-server",
      "args": [
        "--component", "aas-repo",
        "--base-url", "http://localhost:8080"
      ]
    },
    "submodel-repo": {
      "command": "aas-mcp-server",
      "args": [
        "--component", "submodel-repo",
        "--base-url", "http://localhost:8081"
      ]
    },
    "aas-registry": {
      "command": "aas-mcp-server",
      "args": [
        "--component", "aas-registry",
        "--base-url", "http://localhost:8083"
      ]
    },
    "submodel-registry": {
      "command": "aas-mcp-server",
      "args": [
        "--component", "submodel-registry",
        "--base-url", "http://localhost:8084"
      ]
    }
  }
}
```

This allows Claude to access all AAS components simultaneously, each with its own dedicated tool set.

## Supported Implementations

**By default**: Works with any AAS-compliant backend (uses official specs)

**Tested with**:
- ✅ SAP BNAC AAS Server (example derived specs included)
- ✅ Eclipse BaSyx (compatible with official specs)
- ✅ FA³ST Service (compatible with official specs)
- ✅ Custom implementations (generate your own specs)

## Advanced: Path Filtering & Overlays

You can further customize the API surface at runtime using path filtering and overlays.

### Path Filtering

Filter the OpenAPI spec to include only specific paths and HTTP methods using environment variables:

| Component | Environment Variable |
|-----------|---------------------|
| aas-repo | `AAS_REPO_FILTER_PATHS` |
| submodel-repo | `SUBMODEL_REPO_FILTER_PATHS` |
| aas-registry | `AAS_REGISTRY_FILTER_PATHS` |
| submodel-registry | `SUBMODEL_REGISTRY_FILTER_PATHS` |

**Filter Format:**
- `/path` - include all HTTP methods for this path
- `/path:get` - include only GET method
- `/path:get,post` - include GET and POST methods
- Use semicolon (`;`) to separate multiple path filters

**Examples:**
```bash
# Expose only GET /shells
export AAS_REPO_FILTER_PATHS="/shells:get"

# Expose GET and POST for /shells, only GET for /shells/{aasIdentifier}
export AAS_REPO_FILTER_PATHS="/shells:get,post;/shells/{aasIdentifier}:get"

aas-mcp-server --component aas-repo --base-url http://localhost:8080
```

### OpenAPI Overlays

Apply [OpenAPI Overlay](https://github.com/OAI/Overlay-Specification) files to add custom extensions or modify the spec. Place overlay files in `openapi/overlays/` with the naming convention `{component}-overlay.yaml`.

Example overlay (`openapi/overlays/aas-repo-overlay.yaml`):
```yaml
overlay: 1.0.0
info:
  title: AAS Repository MCP Extensions
  version: 1.0.0
actions:
  - target: "$.paths['/shells'].get"
    update:
      operationId: list_shells
      summary: List all Asset Administration Shells
```

## Architecture

This server is a **pure adapter**:

```
┌─────────┐     MCP      ┌──────────────┐    HTTP     ┌────────────────────────┐
│   LLM   │ ◄────────► │ AAS MCP      │ ◄─────── │ Your AAS Backend   │
│ (Claude)│             │ Server       │           │ (SAP BNAC/BaSyx/   │
└─────────┘             │ (This Repo)  │           │  FA³ST/Custom)     │
                        └──────────────┘           └────────────────────────┘
```

**What this server does**:
- Translates MCP protocol ↔ OpenAPI/HTTP
- Applies safety rules (read-only by default, allowlists)
- Provides derived specs for common implementations

**What this server doesn't do**:
- Run AAS backend (you provide that)
- Store AAS data (your backend does that)
- Implement AAS business logic (your backend does that)

### Safety and Curation

The server implements multiple layers of safety:

1. **Read-only by default**: Write operations (POST/PUT/PATCH/DELETE) are blocked unless you explicitly use `--enable-writes`

2. **Allowlist filtering**: Only operations explicitly listed in `DEFAULT_ALLOWLIST` are exposed as MCP tools
   - Currently hardcoded in `src/aas_mcp_server/tool_curation.py`
   - Minimal default: Only `GET /shells` is exposed initially
   - Edit `DEFAULT_ALLOWLIST` to expose additional endpoints

3. **Operation aliasing**: Operations are renamed to be LLM-friendly
   - Example: `GetAllAssetAdministrationShells` → `list_shells`
   - Edit `OPERATION_ID_ALIASES` in `tool_curation.py` to customize

4. **Pagination limits**: Query parameters like `limit` are capped at 100 to prevent excessive responses

**Customizing Exposed Operations:**

You can customize which operations are exposed in two ways:

**Option 1: Using Config Files (Recommended)**
```bash
# Create a config file with curation settings
cat > configs/my-curation.yaml <<EOF
components:
  aas-repo:
    implementation_spec: docs/my-endpoints.json
    official_spec: openapi/AssetAdministrationShellRepositoryServiceSpecification-V3.1.1_SSP-001-resolved.yaml
    curation:
      allowlist:
        - [get, /shells]
        - [post, /shells]
        - [get, /shells/{aasIdentifier}]
      aliases:
        GetAllAssetAdministrationShells: list_shells
        GetAssetAdministrationShellById: get_shell
EOF

# Run server with config
aas-mcp-server \
  --component aas-repo \
  --base-url http://localhost:8080 \
  --config configs/my-curation.yaml
```

**Option 2: Editing Code Directly**
1. Edit `src/aas_mcp_server/tool_curation.py`
2. Add entries to `DEFAULT_ALLOWLIST` (e.g., `(HTTP_METHOD_GET, "/shells/{aasIdentifier}")`)
3. Add entries to `OPERATION_ID_ALIASES` for friendly names

*Note: Config files override hardcoded defaults when `--config` is provided.*

## Development

```bash
# Install in editable mode
pip install -e .

# Run with debug logging
aas-mcp-server --component aas-repo --base-url http://localhost:8080 --log-level DEBUG

# Run tests
pytest

# Generate derived specs for new implementation
python3 scripts/generate_implementation.py --config configs/your-config.yaml

# Validate derived specs
python3 scripts/validate_derived_specs.py
```

## Project Structure

```
aas-mcp-server/
├── src/aas_mcp_server/          # MCP server adapter code
├── openapi/                      # OpenAPI specifications
│   ├── *.yaml                   # Official AAS specs (default)
│   ├── derived/                 # Example derived specs
│   └── overlays/                # Example overlays
├── configs/                      # Implementation configurations
│   ├── sap-bnac-config.example.yaml  # SAP BNAC example
│   ├── config.yaml.template     # Generic template
│   └── README.md                # Configuration guide
├── scripts/                      # Spec generation tools
│   ├── generate_implementation.py   # One-command spec generation
│   ├── generate_filters.py          # Library: Compute endpoint intersections
│   ├── generate_derived_spec.py     # Library: Apply filters + overlays
│   └── validate_derived_specs.py    # Validate specs are up-to-date
├── docs/                         # Implementation endpoint documentation
└── docker-compose.yaml          # Reference backend (testing only)
```

## Quick Reference

### Common Use Cases

**Use Case 1: Production with existing AAS backend (any implementation)**
```bash
# Uses default official AAS specs (works with any compliant backend)
aas-mcp-server --component aas-repo --base-url http://your-backend:8080
```

**Use Case 2: Production with specific backend (optimized)**
```bash
# Uses backend-specific derived spec (filtered to supported endpoints)
aas-mcp-server \
  --component aas-repo \
  --base-url http://your-backend:8080 \
  --openapi openapi/derived/AssetAdministrationShellRepositoryServiceSpecification-V3.1.1_SSP-001-resolved-derived.yaml
```

**Use Case 3: Custom backend (generate your own spec)**
```bash
# 1. Document your endpoints: docs/my-impl-endpoints.json
# 2. Create config: configs/my-impl-config.yaml
# 3. Generate specs:
python3 scripts/generate_implementation.py --config configs/my-impl-config.yaml

# 4. Use generated spec:
aas-mcp-server \
  --component aas-repo \
  --base-url http://your-backend:8080 \
  --openapi openapi/derived/your-derived-spec.yaml
```

**Use Case 4: Development/Testing (no backend yet)**
```bash
# Start reference backend
docker-compose up -d

# Connect MCP server
aas-mcp-server --component aas-repo --base-url http://localhost:8080
```

### Key Files

| File/Directory | Purpose |
|----------------|---------|
| `openapi/*.yaml` | Official AAS specs (default) |
| `openapi/derived/` | Example derived specs |
| `configs/sap-bnac-config.example.yaml` | Example configuration |
| `configs/config.yaml.template` | Generic template for any implementation |
| `scripts/generate_implementation.py` | One-command spec generation |
| `docker-compose.yaml` | Reference backend for testing |

## License

[Your License Here]

## Contributing

Contributions welcome! To add support for a new AAS implementation:

1. Document the implementation's supported endpoints in `docs/`
2. Create a configuration in `configs/` (use `config.yaml.template` as base)
3. Generate derived specs with `scripts/generate_implementation.py`
4. Submit a PR with the new specs and configuration
