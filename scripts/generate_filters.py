#!/usr/bin/env python3
"""
Generate path filter strings for AAS implementation-supported endpoints.

DIAGNOSTIC/ANALYSIS TOOL - For production use, run generate_implementation.py which
orchestrates the full pipeline. This script is useful for:
- Discovering available configurations (--list-configs)
- Analyzing which endpoints your implementation supports (detailed intersection output)
- Debugging filter generation in isolation
- Understanding the intersection between official and implementation specs

This script computes the intersection of:
1. Paths in the official OpenAPI specs (AAS Repo, Submodel Repo, AAS Registry, Submodel Registry)
2. Paths supported by a specific AAS implementation (e.g., SAP BNAC AAS Server, BaSyx, FA³ST)

For each path, it takes the intersection of HTTP methods (only methods in BOTH specs).

Configuration is loaded from YAML files. The configuration file path can be specified via:
1. Command-line argument: --config
2. Environment variable: AAS_IMPLEMENTATION_CONFIG
3. Default: config.yaml.template (users should create their own config)

Output format: Semicolon-separated path filters suitable for generate_derived_spec.py
Example: /shells:get,post;/shells/{aasIdentifier}:get,put,delete

Usage:
    # PRODUCTION: Use the orchestrator (recommended)
    python3 scripts/generate_implementation.py --config configs/my-config.yaml

    # DIAGNOSTIC: Analyze implementation coverage
    python3 scripts/generate_filters.py --config configs/my-implementation-config.yaml

    # DIAGNOSTIC: Discover available configurations
    python3 scripts/generate_filters.py --list-configs

    # DIAGNOSTIC: Debug specific implementation
    python3 scripts/generate_filters.py --config configs/sap-bnac-config.example.yaml
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)

# Constants
DEFAULT_CONFIG_PATH = "configs/config.yaml.template"
CONFIG_ENV_VAR = "AAS_IMPLEMENTATION_CONFIG"
CONFIGS_DIR = "configs"

# OpenAPI spec constants
SPEC_KEY_PATHS = "paths"
SPEC_KEY_NAME = "name"
SPEC_KEY_VERSION = "version"
SPEC_KEY_COMPONENTS = "components"
SPEC_KEY_IMPLEMENTATION_SPEC = "implementation_spec"
SPEC_KEY_OFFICIAL_SPEC = "official_spec"
SPEC_KEY_PATH_PREFIX = "path_prefix"

# File extensions
FILE_EXT_YAML = ".yaml"
FILE_EXT_YML = ".yml"
FILE_EXT_JSON = ".json"

# HTTP methods
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

# Filter string format
FILTER_PATH_SEPARATOR = ";"
FILTER_METHOD_SEPARATOR = ","
FILTER_PATH_METHOD_SEPARATOR = ":"

# Logging separators
LOG_SEPARATOR = "=" * 80
LOG_SEPARATOR_DASH = "-" * 80

# Default values
DEFAULT_UNKNOWN = "Unknown"
DEFAULT_VERSION_UNKNOWN = "unknown"

# Result dictionary keys
RESULT_KEY_ENV_VAR = "env_var"
RESULT_KEY_FILTER_STRING = "filter_string"
RESULT_KEY_PATH_COUNT = "path_count"
RESULT_KEY_OPERATION_COUNT = "operation_count"

# String formatting
EXPORT_CMD_PREFIX = "export"
FILTER_PATHS_SUFFIX = "_FILTER_PATHS"
COMPONENT_NAME_SEPARATOR = "-"
COMPONENT_NAME_REPLACEMENT = "_"
LOG_MSG_INTERSECTION = "Intersection"
LOG_MSG_INTERSECTION_DETAILS = "Intersection details"
LOG_MSG_FILTER_STRING = "Filter string for"
LOG_MSG_FAILED_TO_PROCESS = "Failed to process"
LOG_MSG_SUMMARY = "SUMMARY - Copy these export commands:"
LOG_MSG_STATISTICS = "Statistics:"
LOG_MSG_PATHS = "paths"
LOG_MSG_OPERATIONS = "operations"

# Configuration loading messages
MSG_USING_ENV_VAR = "Using configuration from environment variable"
MSG_USING_DEFAULT = "Using default configuration"
MSG_LOADING_CONFIG = "Loading configuration from"
MSG_CONFIG_NOT_FOUND = "Configuration file not found"
MSG_CREATE_CONFIG = "Please create a configuration file or use --list-configs to see available configurations."
MSG_CONFIG_VIA_OPTIONS = "You can set the configuration via:"
MSG_CONFIG_CLI = "1. Command-line: --config <path>"
MSG_CONFIG_ENV_PREFIX = "2. Environment: export"
MSG_CONFIG_DEFAULT = "3. Default location:"

# List configs messages
MSG_NO_CONFIGS_DIR = "/ directory found."
MSG_CREATE_CONFIGS_DIR = "/ directory with configuration files."
MSG_SEE_EXAMPLES = "See config.yaml.template and sap-bnac-config.example.yaml for examples."
MSG_NO_CONFIG_FILES = "No configuration files found in"
MSG_CREATE_CONFIG_FILE = "Please create a configuration file in"
MSG_AVAILABLE_CONFIGS = "Available configurations in"
MSG_ERROR_READING = "(error reading:"
MSG_DEFAULT_MARKER = " (default)"
MSG_DEFAULT_CONFIG = "Default configuration:"
MSG_ENV_VARIABLE = "Environment variable:"
MSG_CURRENTLY_SET = "Currently set to:"
MSG_NOT_SET = "Currently not set (will use default)"

# Main function messages
MSG_ANALYSIS_HEADER = "AAS IMPLEMENTATION-SUPPORTED ENDPOINTS ANALYSIS"
MSG_IMPLEMENTATION = "Implementation:"

# Argparse messages
ARG_HELP_CONFIG = "Path to implementation configuration file (default: built-in BaSyx config)"
ARG_HELP_LIST_CONFIGS = "List available configuration files"
ARG_HELP_LOG_LEVEL = "Set logging level (default: INFO)"
ARG_DEFAULT_LOG_LEVEL = "INFO"
ARG_LOG_LEVEL_CHOICES = ["DEBUG", "INFO", "WARNING", "ERROR"]

# Argparse argument names
ARG_NAME_CONFIG = "--config"
ARG_NAME_LIST_CONFIGS = "--list-configs"
ARG_NAME_LOG_LEVEL = "--log-level"
ARG_ATTR_CONFIG = "config"
ARG_ATTR_LIST_CONFIGS = "list_configs"
ARG_ATTR_LOG_LEVEL = "log_level"

def load_openapi_yaml(path: str) -> dict[str, Any]:
    """Load OpenAPI spec from YAML file."""
    with open(path) as f:
        return yaml.safe_load(f)


def load_openapi_json(path: str) -> dict[str, Any]:
    """Load OpenAPI spec from JSON file."""
    with open(path) as f:
        return json.load(f)


def load_openapi_file(path: str) -> dict[str, Any]:
    """Load OpenAPI spec from YAML or JSON file based on extension."""
    path_obj = Path(path)
    if path_obj.suffix in [FILE_EXT_YAML, FILE_EXT_YML]:
        return load_openapi_yaml(path)
    elif path_obj.suffix == FILE_EXT_JSON:
        return load_openapi_json(path)
    else:
        raise ValueError(f"Unsupported file extension: {path_obj.suffix}")


def extract_paths_and_methods(spec: dict[str, Any]) -> dict[str, set[str]]:
    """
    Extract paths and their HTTP methods from OpenAPI spec.

    Returns:
        dict mapping path string to set of lowercase method names (e.g., {'get', 'post'})
    """
    result = {}
    for path, operations in spec.get(SPEC_KEY_PATHS, {}).items():
        methods = {
            method.lower()
            for method in operations.keys()
            if method.lower() in HTTP_METHODS
        }
        if methods:
            result[path] = methods
    return result


def compute_intersection(
    official_paths: dict[str, set[str]], implementation_paths: dict[str, set[str]]
) -> dict[str, set[str]]:
    """
    Compute the intersection of paths and methods.

    Only includes paths that exist in BOTH specs.
    For each path, only includes methods that exist in BOTH specs.

    Returns:
        dict mapping path to set of methods that exist in both specs
    """
    intersection = {}
    for path in set(official_paths.keys()) & set(implementation_paths.keys()):
        common_methods = official_paths[path] & implementation_paths[path]
        if common_methods:
            intersection[path] = common_methods
    return intersection


def format_filter_string(paths_methods: dict[str, set[str]]) -> str:
    """
    Format paths and methods as a filter string for generate_derived_spec.py.

    Format: /path:method1,method2;/path2:method3
    """
    parts = []
    for path in sorted(paths_methods.keys()):
        methods = sorted(paths_methods[path])
        parts.append(f"{path}{FILTER_PATH_METHOD_SEPARATOR}{FILTER_METHOD_SEPARATOR.join(methods)}")
    return FILTER_PATH_SEPARATOR.join(parts)


def filter_by_prefix(paths_methods: dict[str, set[str]], prefix: str | None) -> dict[str, set[str]]:
    """
    Filter paths to only those starting with the given prefix.

    If prefix is None, return all paths.
    """
    if prefix is None:
        return paths_methods
    return {path: methods for path, methods in paths_methods.items() if path.startswith(prefix)}


def load_config(config_path: str | None) -> dict[str, Any]:
    """
    Load configuration from YAML file.

    Priority:
    1. Command-line argument (--config)
    2. Environment variable (AAS_IMPLEMENTATION_CONFIG)
    3. Default (configs/basyx-config.yaml)

    Args:
        config_path: Path to configuration file from command-line, or None

    Returns:
        Configuration dictionary
    """
    # Determine config path with priority
    if config_path is None:
        config_path = os.getenv(CONFIG_ENV_VAR, DEFAULT_CONFIG_PATH)

        if os.getenv(CONFIG_ENV_VAR):
            logging.info(f"{MSG_USING_ENV_VAR} {CONFIG_ENV_VAR}")
        else:
            logging.info(MSG_USING_DEFAULT)

    if not Path(config_path).exists():
        raise FileNotFoundError(
            f"{MSG_CONFIG_NOT_FOUND}: {config_path}\n"
            f"{MSG_CREATE_CONFIG}\n"
            f"{MSG_CONFIG_VIA_OPTIONS}\n"
            f"  {MSG_CONFIG_CLI}\n"
            f"  {MSG_CONFIG_ENV_PREFIX} {CONFIG_ENV_VAR}=<path>\n"
            f"  {MSG_CONFIG_DEFAULT} {DEFAULT_CONFIG_PATH}"
        )

    logging.info(f"{MSG_LOADING_CONFIG}: {config_path}")
    with open(config_path) as f:
        return yaml.safe_load(f)


def list_available_configs():
    """List available configuration files in the configs/ directory."""
    configs_dir = Path(CONFIGS_DIR)
    if not configs_dir.exists():
        logging.error(f"No {CONFIGS_DIR}{MSG_NO_CONFIGS_DIR}")
        logging.info(f"\nPlease create a {CONFIGS_DIR}{MSG_CREATE_CONFIGS_DIR}")
        logging.info(MSG_SEE_EXAMPLES)
        return

    config_files = list(configs_dir.glob(f"*{FILE_EXT_YAML}")) + list(configs_dir.glob(f"*{FILE_EXT_YML}"))
    if not config_files:
        logging.error(f"{MSG_NO_CONFIG_FILES} {CONFIGS_DIR}/ directory.")
        logging.info(f"\n{MSG_CREATE_CONFIG_FILE} {CONFIGS_DIR}/")
        logging.info(MSG_SEE_EXAMPLES)
        return

    logging.info(f"{MSG_AVAILABLE_CONFIGS} {CONFIGS_DIR}/:")
    for config_file in sorted(config_files):
        try:
            with open(config_file) as f:
                config = yaml.safe_load(f)
                name = config.get(SPEC_KEY_NAME, config_file.stem)
                version = config.get(SPEC_KEY_VERSION, DEFAULT_VERSION_UNKNOWN)
                is_default = str(config_file) == DEFAULT_CONFIG_PATH
                default_marker = MSG_DEFAULT_MARKER if is_default else ""
                logging.info(f"  - {config_file}: {name} {version}{default_marker}")
        except Exception as e:
            logging.warning(f"  - {config_file}: {MSG_ERROR_READING} {e})")

    logging.info(f"\n{MSG_DEFAULT_CONFIG} {DEFAULT_CONFIG_PATH}")
    logging.info(f"{MSG_ENV_VARIABLE} {CONFIG_ENV_VAR}")

    current_env = os.getenv(CONFIG_ENV_VAR)
    if current_env:
        logging.info(f"{MSG_CURRENTLY_SET} {current_env}")
    else:
        logging.info(MSG_NOT_SET)


def process_component(
    component_config: dict[str, Any]
) -> tuple[dict[str, set[str]], str]:
    """
    Process a single component and return intersection and filter string.

    Returns:
        Tuple of (intersection dict, filter string)
    """
    # Load implementation spec
    impl_spec_path = component_config[SPEC_KEY_IMPLEMENTATION_SPEC]
    logging.debug(f"  Loading implementation spec: {impl_spec_path}")
    impl_spec = load_openapi_file(impl_spec_path)
    impl_paths = extract_paths_and_methods(impl_spec)

    # Load official spec
    official_spec_path = component_config[SPEC_KEY_OFFICIAL_SPEC]
    logging.debug(f"  Loading official spec: {official_spec_path}")
    official_spec = load_openapi_yaml(official_spec_path)
    official_paths = extract_paths_and_methods(official_spec)

    # Apply path prefix filter if specified
    path_prefix = component_config.get(SPEC_KEY_PATH_PREFIX)
    if path_prefix:
        impl_paths = filter_by_prefix(impl_paths, path_prefix)
        official_paths = filter_by_prefix(official_paths, path_prefix)

    # Compute intersection
    intersection = compute_intersection(official_paths, impl_paths)

    # Generate filter string
    filter_string = format_filter_string(intersection)

    return intersection, filter_string


def generate_filters(config_path: str | None = None, verbose: bool = True) -> dict[str, str]:
    """
    Generate filter strings for all components in the configuration.

    This is the main library function that can be called programmatically.

    Args:
        config_path: Path to configuration file. If None, uses environment variable or default.
        verbose: If True, prints detailed progress information

    Returns:
        Dictionary mapping environment variable names to filter string values
        Example: {"AAS_REPO_FILTER_PATHS": "/shells:get,post;...", ...}
    """
    # Load configuration
    config = load_config(config_path)
    config_name = config.get(SPEC_KEY_NAME, DEFAULT_UNKNOWN)
    config_version = config.get(SPEC_KEY_VERSION, "")

    if verbose:
        logging.info(LOG_SEPARATOR)
        logging.info(MSG_ANALYSIS_HEADER)
        logging.info(f"{MSG_IMPLEMENTATION} {config_name} {config_version}")
        logging.info(LOG_SEPARATOR)

    # Process each component
    results = {}
    for component_name, component_config in config[SPEC_KEY_COMPONENTS].items():
        if verbose:
            logging.info(f"\n[{component_name.upper().replace(COMPONENT_NAME_SEPARATOR, ' ')}]")

        try:
            intersection, filter_string = process_component(component_config)

            if verbose:
                logging.info(f"  {LOG_MSG_INTERSECTION}: {len(intersection)} {LOG_MSG_PATHS}")
                logging.info(f"\n  {LOG_MSG_INTERSECTION_DETAILS}:")
                for path in sorted(intersection.keys()):
                    methods = sorted(intersection[path])
                    logging.info(f"    {path}: {methods}")

            # Store results
            env_var = f"{component_name.upper().replace(COMPONENT_NAME_SEPARATOR, COMPONENT_NAME_REPLACEMENT)}{FILTER_PATHS_SUFFIX}"
            results[env_var] = filter_string

            if verbose:
                logging.info(f"\n  {LOG_MSG_FILTER_STRING} {component_name}:")
                logging.info(f"    {EXPORT_CMD_PREFIX} {env_var}=\"{filter_string}\"")

        except Exception as e:
            logging.error(f"  {LOG_MSG_FAILED_TO_PROCESS} {component_name}: {e}")
            continue

    # Summary
    if verbose:
        logging.info(f"\n{LOG_SEPARATOR}")
        logging.info(LOG_MSG_SUMMARY)
        logging.info(LOG_SEPARATOR)
        for env_var, filter_string in results.items():
            logging.info(f'{EXPORT_CMD_PREFIX} {env_var}="{filter_string}"')
        logging.info(LOG_SEPARATOR)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Generate filter path strings for AAS implementation endpoints.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        ARG_NAME_CONFIG,
        help=ARG_HELP_CONFIG,
    )
    parser.add_argument(
        ARG_NAME_LIST_CONFIGS,
        action="store_true",
        help=ARG_HELP_LIST_CONFIGS,
    )
    parser.add_argument(
        ARG_NAME_LOG_LEVEL,
        default=ARG_DEFAULT_LOG_LEVEL,
        choices=ARG_LOG_LEVEL_CHOICES,
        help=ARG_HELP_LOG_LEVEL,
    )

    args = parser.parse_args()

    # Set logging level
    logging.getLogger().setLevel(getattr(args, ARG_ATTR_LOG_LEVEL))

    # Handle --list-configs
    if getattr(args, ARG_ATTR_LIST_CONFIGS):
        list_available_configs()
        return

    # Generate filters using library function
    results = generate_filters(
        config_path=getattr(args, ARG_ATTR_CONFIG),
        verbose=True
    )

    # Print statistics
    logging.info(f"\n{LOG_MSG_STATISTICS}")
    for env_var, filter_string in results.items():
        # Count paths and operations from filter string
        path_count = len(filter_string.split(FILTER_PATH_SEPARATOR)) if filter_string else 0
        operation_count = filter_string.count(FILTER_METHOD_SEPARATOR) + path_count if filter_string else 0
        component_name = env_var.replace(FILTER_PATHS_SUFFIX, "").lower().replace(COMPONENT_NAME_REPLACEMENT, COMPONENT_NAME_SEPARATOR)
        logging.info(f"  {component_name}: {path_count} {LOG_MSG_PATHS}, {operation_count} {LOG_MSG_OPERATIONS}")
    logging.info(LOG_SEPARATOR)


if __name__ == "__main__":
    main()
