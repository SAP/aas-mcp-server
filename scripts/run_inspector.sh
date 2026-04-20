#!/usr/bin/env bash
set -euo pipefail

# Run MCP Inspector to test/debug the AAS MCP server interactively.
#
# The MCP Inspector provides a browser-based UI to:
# - Explore available MCP tools
# - Test tool parameters and responses
# - Debug OpenAPI spec to MCP tool conversion
#
# Usage:
#   # Test AAS Repository component
#   ./scripts/run_inspector.sh
#
#   # Test specific component
#   AAS_COMPONENT=submodel-repo ./scripts/run_inspector.sh
#
#   # Use custom backend URL
#   AAS_BASE_URL=http://prod-server:8081 ./scripts/run_inspector.sh
#
#   # Use derived spec for specific implementation
#   AAS_OPENAPI_PATH=openapi/derived/AssetAdministrationShellRepositoryServiceSpecification-V3.1.1_SSP-001-resolved-derived.yaml ./scripts/run_inspector.sh
#
# Environment variables:
#   AAS_COMPONENT       - Component to test (default: aas-repo)
#                         Options: aas-repo, submodel-repo, aas-registry, submodel-registry
#   AAS_BASE_URL        - Backend AAS server URL (default: http://localhost:8080)
#   AAS_OPENAPI_PATH    - OpenAPI spec path (default: official spec for component)
#   AAS_MCP_ENABLE_WRITES - Set to "1" to enable write operations (default: read-only)

# Set defaults
COMPONENT="${AAS_COMPONENT:-aas-repo}"
BASE_URL="${AAS_BASE_URL:-http://localhost:8080}"

# Determine default OpenAPI path based on component if not specified
if [ -z "${AAS_OPENAPI_PATH:-}" ]; then
  case "$COMPONENT" in
    aas-repo)
      DEFAULT_OPENAPI="openapi/AssetAdministrationShellRepositoryServiceSpecification-V3.1.1_SSP-001-resolved.yaml"
      ;;
    submodel-repo)
      DEFAULT_OPENAPI="openapi/SubmodelRepositoryServiceSpecification-V3.1.1_SSP-001-resolved.yaml"
      ;;
    aas-registry)
      DEFAULT_OPENAPI="openapi/AssetAdministrationShellRegistryServiceSpecification-V3.1.1_SSP-001-resolved.yaml"
      ;;
    submodel-registry)
      DEFAULT_OPENAPI="openapi/SubmodelRegistryServiceSpecification-V3.1.1_SSP-001-resolved.yaml"
      ;;
    *)
      echo "Error: Unknown component: $COMPONENT"
      echo "Valid components: aas-repo, submodel-repo, aas-registry, submodel-registry"
      exit 1
      ;;
  esac
  OPENAPI_PATH="$DEFAULT_OPENAPI"
else
  OPENAPI_PATH="$AAS_OPENAPI_PATH"
fi

echo "========================================"
echo "MCP Inspector Configuration"
echo "========================================"
echo "Component:    $COMPONENT"
echo "Base URL:     $BASE_URL"
echo "OpenAPI Spec: $OPENAPI_PATH"
echo "Write Mode:   ${AAS_MCP_ENABLE_WRITES:-disabled (read-only)}"
echo "========================================"
echo ""
echo "Starting MCP Inspector..."
echo "The browser will open automatically with the MCP testing UI."
echo ""

npx @modelcontextprotocol/inspector -- aas-mcp-server \
  --component "$COMPONENT" \
  --base-url "$BASE_URL" \
  --openapi "$OPENAPI_PATH"
