"""
Command-line interface for AAS MCP Server.

This module provides the main CLI entry point for running the AAS MCP server.
It handles argument parsing, configuration loading, and server initialization.

Supports multiple AAS components:
- aas-repo: Asset Administration Shell Repository
- submodel-repo: Submodel Repository
- aas-registry: AAS Registry
- submodel-registry: Submodel Registry

Each component can be configured via command-line arguments or environment variables.
"""

import argparse
import os
from .server import build_mcp_server

# Constants for environment variables
ENV_VAR_MCP_TRANSPORT = "MCP_TRANSPORT"
ENV_VAR_AAS_MCP_ENABLE_WRITES = "AAS_MCP_ENABLE_WRITES"
ENV_VAR_LOG_LEVEL = "LOG_LEVEL"
ENV_VAR_AAS_BASE_URL = "AAS_BASE_URL"
ENV_VAR_AAS_OPENAPI_PATH = "AAS_OPENAPI_PATH"

# Constants for default values
DEFAULT_TRANSPORT = "stdio"
DEFAULT_LOG_LEVEL = "INFO"
ENABLE_WRITES_TRUE_VALUE = "1"

# Constants for CLI program
CLI_PROGRAM_NAME = "aas-mcp-server"
CLI_DESCRIPTION = "AAS MCP Server (OpenAPI → MCP) - Support for multiple AAS components"

# Constants for argument names
ARG_COMPONENT = "--component"
ARG_BASE_URL = "--base-url"
ARG_OPENAPI = "--openapi"
ARG_TRANSPORT = "--transport"
ARG_ENABLE_WRITES = "--enable-writes"
ARG_LOG_LEVEL = "--log-level"

# Constants for component configuration keys
CONFIG_KEY_OPENAPI = "openapi"
CONFIG_KEY_DEFAULT_URL = "default_url"
CONFIG_KEY_DESCRIPTION = "description"

# Component-to-OpenAPI mapping
# By default, uses official AAS specifications (full, unfiltered)
# Users can override with --openapi flag to use derived specs or custom specs
COMPONENT_CONFIGS = {
    "aas-repo": {
        CONFIG_KEY_OPENAPI: "openapi/AssetAdministrationShellRepositoryServiceSpecification-V3.1.1_SSP-001-resolved.yaml",
        CONFIG_KEY_DEFAULT_URL: "http://localhost:8080",
        CONFIG_KEY_DESCRIPTION: "AAS Repository - Manage Asset Administration Shells",
    },
    "submodel-repo": {
        CONFIG_KEY_OPENAPI: "openapi/SubmodelRepositoryServiceSpecification-V3.1.1_SSP-001-resolved.yaml",
        CONFIG_KEY_DEFAULT_URL: "http://localhost:8081",
        CONFIG_KEY_DESCRIPTION: "Submodel Repository - Manage Submodels",
    },
    "aas-registry": {
        CONFIG_KEY_OPENAPI: "openapi/AssetAdministrationShellRegistryServiceSpecification-V3.1.1_SSP-001-resolved.yaml",
        CONFIG_KEY_DEFAULT_URL: "http://localhost:8083",
        CONFIG_KEY_DESCRIPTION: "AAS Registry - Discover and register AAS components",
    },
    "submodel-registry": {
        CONFIG_KEY_OPENAPI: "openapi/SubmodelRegistryServiceSpecification-V3.1.1_SSP-001-resolved.yaml",
        CONFIG_KEY_DEFAULT_URL: "http://localhost:8084",
        CONFIG_KEY_DESCRIPTION: "Submodel Registry - Discover and register Submodels",
    },
}

def main() -> None:
    """
    Main entry point for the AAS MCP Server CLI.

    Parses command-line arguments, loads component configuration,
    builds the MCP server, and starts it with the specified transport.

    The function handles:
    - Argument parsing and validation
    - Configuration resolution (CLI args > env vars > defaults)
    - MCP server initialization
    - Server execution

    Exits:
        The function runs the MCP server and does not return.
    """
    p = argparse.ArgumentParser(
        prog=CLI_PROGRAM_NAME,
        description=CLI_DESCRIPTION
    )
    p.add_argument(
        ARG_COMPONENT,
        required=True,
        choices=list(COMPONENT_CONFIGS.keys()),
        help="AAS component to serve"
    )
    p.add_argument(
        ARG_BASE_URL,
        help="Base URL for the component API (overrides component default)"
    )
    p.add_argument(
        ARG_OPENAPI,
        help="Custom OpenAPI spec path (overrides component default)"
    )
    p.add_argument(
        ARG_TRANSPORT,
        default=os.getenv(ENV_VAR_MCP_TRANSPORT, DEFAULT_TRANSPORT),
        choices=[DEFAULT_TRANSPORT]
    )
    p.add_argument(
        ARG_ENABLE_WRITES,
        action="store_true",
        default=os.getenv(ENV_VAR_AAS_MCP_ENABLE_WRITES) == ENABLE_WRITES_TRUE_VALUE
    )
    p.add_argument(
        ARG_LOG_LEVEL,
        default=os.getenv(ENV_VAR_LOG_LEVEL, DEFAULT_LOG_LEVEL)
    )

    args = p.parse_args()

    # Get component configuration
    component_config = COMPONENT_CONFIGS[args.component]

    # Use provided values or fall back to component defaults
    base_url = (
        args.base_url
        or os.getenv(ENV_VAR_AAS_BASE_URL)
        or component_config[CONFIG_KEY_DEFAULT_URL]
    )
    openapi_path = (
        args.openapi
        or os.getenv(ENV_VAR_AAS_OPENAPI_PATH)
        or component_config[CONFIG_KEY_OPENAPI]
    )

    mcp = build_mcp_server(
        base_url=base_url,
        openapi_path=openapi_path,
        enable_writes=args.enable_writes,
        log_level=args.log_level,
        component_name=args.component,
    )
    mcp.run(transport=args.transport)

if __name__ == "__main__":
    main()
