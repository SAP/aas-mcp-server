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
#   # Test AAS Repository component (requires config.yaml)
#   ./scripts/run_inspector.sh
#
#   # Test specific component
#   AAS_COMPONENT=submodel-repo ./scripts/run_inspector.sh
#
#   # Use custom backend URL
#   AAS_BASE_URL=http://prod-server:8081 ./scripts/run_inspector.sh
#
#   # Use custom config file
#   CONFIG_PATH=/path/to/config.yaml ./scripts/run_inspector.sh
#
# Environment variables:
#   AAS_COMPONENT       - Component to test (default: aas-repo)
#                         Options: aas-repo, submodel-repo, aas-registry, submodel-registry
#   AAS_BASE_URL        - Backend AAS server URL (default: http://localhost:8080)
#   CONFIG_PATH         - Path to config.yaml (default: config.yaml in current directory)
#   AAS_MCP_ENABLE_WRITES - Set to "1" to enable write operations (default: read-only)

# Set defaults
COMPONENT="${AAS_COMPONENT:-aas-repo}"
BASE_URL="${AAS_BASE_URL:-http://localhost:8081}"
CONFIG_PATH="${CONFIG_PATH:-config.yaml}"
ENABLE_WRITES="${AAS_MCP_ENABLE_WRITES:-1}"  # Default: disabled (read-only)

# Check if config file exists
if [ ! -f "$CONFIG_PATH" ]; then
  echo "ERROR Error: Configuration file not found: $CONFIG_PATH"
  echo ""
  echo "Please create a config.yaml file or set CONFIG_PATH environment variable."
  echo ""
  echo "Example config.yaml:"
  echo "  components:"
  echo "    aas-repo:"
  echo "      official_spec: specs/AssetAdministrationShellRepositoryServiceSpecification-V3.1.1_SSP-001.yaml"
  echo ""
  echo "See config.yaml.example for a complete template."
  exit 1
fi

echo "========================================"
echo "MCP Inspector Configuration"
echo "========================================"
echo "Component:    $COMPONENT"
echo "Base URL:     $BASE_URL"
echo "Config File:  $CONFIG_PATH"
if [ "$ENABLE_WRITES" = "1" ]; then
  echo "Write Mode:   enabled"
else
  echo "Write Mode:   disabled (read-only)"
fi
echo "========================================"
echo ""
echo "Starting MCP Inspector..."
echo "The browser will open automatically with the MCP testing UI."
echo ""

# Build command with conditional --enable-writes flag
CMD="npx @modelcontextprotocol/inspector -- aas-mcp-server \
  --component \"$COMPONENT\" \
  --base-url \"$BASE_URL\" \
  --config \"$CONFIG_PATH\" \
  --log-level DEBUG"

# Add --enable-writes if environment variable is set
if [ "$ENABLE_WRITES" = "1" ]; then
  CMD="$CMD --enable-writes"
fi

eval "$CMD"
