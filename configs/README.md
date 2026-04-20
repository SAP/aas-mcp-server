# Implementation Configurations

This directory contains configuration files for generating implementation-specific derived OpenAPI specifications. Use these configurations to adapt the official AAS specifications to match what your AAS implementation actually supports.

## Quick Start

1. **Copy the template:**
   ```bash
   cp configs/config.yaml.template configs/my-implementation-config.yaml
   ```

2. **Customize the configuration:**
   - Update `name`, `version`, and `description` for your implementation
   - Set `implementation_spec` paths to your endpoint documentation
   - Adjust `path_prefix` values as needed
   - (Optional) Add overlay paths for customization
   - (Optional) Add curation settings to control exposed operations

3. **Generate derived specs:**
   ```bash
   python3 scripts/generate_implementation.py --config configs/my-implementation-config.yaml
   ```

4. **Run MCP server with curation settings:**
   ```bash
   aas-mcp-server \
     --component aas-repo \
     --base-url http://your-backend:8080 \
     --config configs/my-implementation-config.yaml
   ```

## Files

- **`config.yaml.template`** - Generic template for any AAS implementation. Start here.
- **`sap-bnac-config.example.yaml`** - Example configuration for SAP BNAC AAS Server. Reference implementation.
- **`README.md`** - This file. Configuration documentation.

## Configuration File Structure

```yaml
name: Your Implementation Name
version: v1.0
description: Brief description

components:
  aas-repo:
    implementation_spec: docs/your-endpoints.json    # What you actually support
    official_spec: openapi/official-spec.yaml        # Official AAS specification
    path_prefix: /shells                             # Optional: filter by prefix
    description: Component description               # Optional
    overlay: openapi/overlays/custom-overlay.yaml    # Optional: customization
```

### Required Fields

- **`name`**: Human-readable implementation name
- **`version`**: Version string (e.g., "v1.0")
- **`description`**: Brief description of the implementation

For each component:
- **`implementation_spec`**: Path to OpenAPI spec documenting your implementation's endpoints (JSON or YAML)
- **`official_spec`**: Path to official AAS specification from `openapi/` directory

### Optional Fields

- **`path_prefix`**: Filter implementation spec paths by prefix
  - Use when one spec file covers multiple components
  - Example: `/shells` for aas-repo, `/submodels` for submodel-repo
  - Set to `null` when spec contains only one component

- **`overlay`**: Path to OpenAPI Overlay file for customization
  - Rename operations for better LLM understanding
  - Update descriptions and add extensions
  - See [OpenAPI Overlay Specification](https://github.com/OAI/Overlay-Specification)

- **`curation`**: Allowlist and aliases for tool exposure
  - **Fully supported!** These settings override the hardcoded defaults in `tool_curation.py`
  - If omitted, the server uses default values from `tool_curation.py`
  - Use `--config` flag to load curation settings at runtime
  ```yaml
  curation:
    allowlist:                   # List of [method, path] tuples to expose
      - [get, /shells]
      - [post, /shells]
    aliases:                     # Map operationId to LLM-friendly names
      GetAllAssetAdministrationShells: list_shells
  ```

## Supported Components

Configure any combination of these AAS components:

- **`aas-repo`**: Asset Administration Shell Repository
- **`submodel-repo`**: Submodel Repository
- **`aas-registry`**: AAS Registry
- **`submodel-registry`**: Submodel Registry

Additional AAS repositories and registries (e.g., Concept Description Repository) will be supported in future releases.

## Creating Implementation Documentation

Before creating a configuration, you need to document which endpoints your implementation supports:

### Option 1: Export from Implementation

If your implementation can export its OpenAPI specification:
```bash
# Export from your running server
curl http://your-server:8080/v3/api-docs > docs/your-impl-endpoints.json
```

### Option 2: Manual Documentation

Create an OpenAPI spec (JSON or YAML) listing all supported paths and methods:

```json
{
  "openapi": "3.0.3",
  "info": {
    "title": "My Implementation Endpoints",
    "version": "1.0"
  },
  "paths": {
    "/shells": {
      "get": {},
      "post": {}
    },
    "/shells/{aasIdentifier}": {
      "get": {},
      "put": {},
      "delete": {}
    }
  }
}
```

Save in `docs/` directory and reference in your config file.

## Pipeline Overview

The configuration file is used by these tools:

### 1. Generate All Specs (Recommended)

Single command that orchestrates the entire pipeline:

```bash
python3 scripts/generate_implementation.py --config configs/your-config.yaml

# Dry-run to preview
python3 scripts/generate_implementation.py --config configs/your-config.yaml --dry-run
```

The `generate_implementation.py` script handles the entire pipeline automatically, including filter generation and derived spec creation for all components.

### 2. Validation

Verify derived specs are up-to-date:
```bash
python3 scripts/validate_derived_specs.py --config configs/your-config.yaml
```

## How It Works

The `generate_implementation.py` script orchestrates the entire pipeline:

1. **Intersection Computation**: Compares your `implementation_spec` with the `official_spec`
2. **Path Filtering**: Applies `path_prefix` filter if specified
3. **Overlay Application**: Applies OpenAPI Overlay transformations if provided
4. **Derived Spec Output**: Writes filtered + customized specs to `openapi/derived/`

The pipeline uses internal library modules (`generate_filters.py` and `generate_derived_spec.py`) to perform these operations.

The derived specs can then be used with the MCP server:
```bash
aas-mcp-server --component aas-repo --openapi openapi/derived/aas-repo-derived.yaml
```

### Example 1: Single Spec Per Component

```yaml
# Your implementation has separate spec files for each component
name: Custom Server
version: v1.0

components:
  aas-repo:
    implementation_spec: docs/custom-aas-repo.json
    official_spec: openapi/AssetAdministrationShellRepositoryServiceSpecification-V3.1.1_SSP-001-resolved.yaml
    path_prefix: null  # No filtering needed
```

### Example 2: Combined Spec with Filtering

```yaml
# Your implementation has one spec covering multiple components
name: Unified Server
version: v2.0

components:
  aas-repo:
    implementation_spec: docs/unified-server.json  # Contains /shells and /submodels
    official_spec: openapi/AssetAdministrationShellRepositoryServiceSpecification-V3.1.1_SSP-001-resolved.yaml
    path_prefix: /shells  # Filter to only /shells paths

  submodel-repo:
    implementation_spec: docs/unified-server.json  # Same spec
    official_spec: openapi/SubmodelRepositoryServiceSpecification-V3.1.1_SSP-001-resolved.yaml
    path_prefix: /submodels  # Filter to only /submodels paths
```

### Example 3: With Overlays

```yaml
# Customize operation names for better LLM understanding
name: LLM-Friendly Server
version: v1.0

components:
  aas-repo:
    implementation_spec: docs/server-endpoints.json
    official_spec: openapi/AssetAdministrationShellRepositoryServiceSpecification-V3.1.1_SSP-001-resolved.yaml
    path_prefix: null
    overlay: openapi/overlays/custom-aas-repo-overlay.yaml  # Rename operations
```

## Default Behavior

The MCP server defaults to using **official AAS specifications** (unfiltered, full spec). You only need derived specs if:
- Your implementation supports a **subset** of the official specification
- You want to **prevent LLMs** from attempting unsupported endpoints
- You want to **customize** operation names and descriptions via overlays

## Troubleshooting

### "No paths match the intersection"
- Check that `implementation_spec` path is correct
- Verify `path_prefix` matches your spec's paths
- Ensure `implementation_spec` contains OpenAPI format with `paths` key

### "Overlay file not found"
- Check overlay path is relative to project root
- Verify overlay file exists at specified path
- Overlay is optional - remove the line if not needed

### "Invalid YAML format"
- Validate YAML syntax (indentation matters!)
- Use a YAML validator or linter
- Check for special characters that need quoting

## Additional Resources

- **Official AAS Specifications**: `openapi/` directory
- **Overlay Examples**: `openapi/overlays/` directory
- **Example Endpoint Documentation**: `docs/` directory
- **Script Documentation**: See `scripts/` directory README files
