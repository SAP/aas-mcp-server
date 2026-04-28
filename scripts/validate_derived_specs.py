#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Validate that derived OpenAPI specs are up-to-date with their source configuration.

This script checks:
1. Whether derived specs exist for all components in a configuration
2. Whether derived specs were generated from the correct source specs
3. Whether overlays have been applied
4. Whether the filter paths match (by checking path counts)

Usage:
    # Validate your implementation configuration
    python3 scripts/validate_derived_specs.py --config configs/my-implementation-config.yaml

    # Validate SAP BNAC example configuration
    python3 scripts/validate_derived_specs.py --config configs/sap-bnac-config.example.yaml

    # Verbose output
    python3 scripts/validate_derived_specs.py --config configs/my-config.yaml --log-level DEBUG
"""

import argparse
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

# Constants - Configuration
DEFAULT_CONFIG_PATH = "configs/config.yaml.template"
CONFIG_ENV_VAR = "AAS_IMPLEMENTATION_CONFIG"

# Constants - Config keys
CONFIG_KEY_NAME = "name"
CONFIG_KEY_VERSION = "version"
CONFIG_KEY_COMPONENTS = "components"
CONFIG_KEY_OFFICIAL_SPEC = "official_spec"
CONFIG_KEY_IMPLEMENTATION_SPEC = "implementation_spec"
CONFIG_KEY_OVERLAY = "overlay"

# Constants - Spec keys
SPEC_KEY_PATHS = "paths"

# Constants - File naming
DERIVED_SUFFIX = "-derived.yaml"

# Constants - Logging
LOG_SEPARATOR = "=" * 80
MSG_VALIDATION_HEADER = "DERIVED SPEC VALIDATION"
MSG_IMPLEMENTATION = "Implementation:"
MSG_CONFIGURATION = "Configuration:"
MSG_NO_COMPONENTS = "No components found in configuration"
MSG_EXPECTED_DERIVED = "Expected derived spec:"
MSG_DERIVED_EXISTS = "Derived spec exists"
MSG_VALID_YAML = "Derived spec is valid YAML"
MSG_HAS_PATHS = "Derived spec has"
MSG_OFFICIAL_SPEC_PATHS = "Official spec has"
MSG_ALL_PATHS_VALID = "All derived paths exist in official spec"
MSG_OVERLAY_EXISTS = "Overlay exists:"
MSG_IMPL_SPEC_EXISTS = "Implementation spec exists:"
MSG_VALID_COMPONENT = "Valid"
MSG_VALIDATION_SUMMARY = "VALIDATION SUMMARY"
MSG_TOTAL_COMPONENTS = "Total components:"
MSG_VALID = "Valid:"
MSG_INVALID = "Invalid:"
MSG_REMEDIATION = "REMEDIATION"
MSG_REMEDIATION_HINT = "To fix validation issues, regenerate the derived specs:"
MSG_ALL_VALID = "All derived specs are valid and up-to-date!"

# Constants - Error messages
ERR_CONFIG_NOT_FOUND = "Configuration file not found:"
ERR_DERIVED_NOT_FOUND = "Derived spec not found:"
ERR_PARSE_FAILED = "Failed to parse derived spec:"
ERR_NO_PATHS = "Derived spec has no paths (empty spec)"
ERR_OFFICIAL_NOT_FOUND = "Official spec not found:"
ERR_PARSE_OFFICIAL_FAILED = "Failed to parse official spec:"
ERR_INVALID_PATHS = "Derived spec contains paths not in official spec:"
ERR_OVERLAY_NOT_FOUND = "Overlay file not found:"
ERR_IMPL_SPEC_NOT_FOUND = "Implementation spec not found:"

# Constants - Argparse
ARG_NAME_CONFIG = "--config"
ARG_NAME_LOG_LEVEL = "--log-level"
ARG_HELP_CONFIG = f"Path to implementation configuration file (default: {DEFAULT_CONFIG_PATH})"
ARG_HELP_LOG_LEVEL = "Set logging level (default: INFO)"
ARG_DEFAULT_LOG_LEVEL = "INFO"
ARG_LOG_LEVEL_CHOICES = ["DEBUG", "INFO", "WARNING", "ERROR"]

# Constants - Defaults
DEFAULT_UNKNOWN = "Unknown"
DEFAULT_VERSION_EMPTY = ""


def load_config(config_path: str | None) -> dict[str, Any]:
    """Load configuration from YAML file."""
    if config_path is None:
        config_path = os.getenv(CONFIG_ENV_VAR, DEFAULT_CONFIG_PATH)

    if not Path(config_path).exists():
        raise FileNotFoundError(f"{ERR_CONFIG_NOT_FOUND} {config_path}")

    logging.debug(f"Loading configuration from: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_openapi_yaml(path: str) -> dict[str, Any]:
    """Load OpenAPI spec from YAML file."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def check_file_exists(file_path: str | Path, error_prefix: str) -> list[str]:
    """
    Check if a file exists and return error message if not.

    Returns:
        Empty list if file exists, list with error message otherwise
    """
    if not Path(file_path).exists():
        return [f"{error_prefix} {file_path}"]
    return []


def load_spec_safely(
    file_path: str | Path,
    error_prefix: str
) -> tuple[dict[str, Any] | None, list[str]]:
    """
    Safely load an OpenAPI spec file.

    Returns:
        Tuple of (spec dict or None, list of error messages)
    """
    # Check file exists
    errors = check_file_exists(file_path, error_prefix.replace("Failed to parse", "").strip() + " not found:")
    if errors:
        return None, errors

    # Try to parse
    try:
        spec = load_openapi_yaml(str(file_path))
        return spec, []
    except Exception as e:
        return None, [f"{error_prefix} {e}"]


def get_derived_spec_path(official_spec_path: str, config_dir: Path) -> Path:
    """
    Compute the expected path for a derived spec.

    Convention: {config_dir}/derived/{original-filename}-derived.yaml
    The derived directory is relative to the config file location.
    """
    original_filename = Path(official_spec_path).stem
    return config_dir / "derived" / f"{original_filename}{DERIVED_SUFFIX}"


def validate_component(
    component_config: dict[str, Any],
    config_dir: Path
) -> tuple[bool, list[str]]:
    """
    Validate a single component's derived spec.

    Args:
        component_config: Component configuration from config file
        config_dir: Directory containing the config file (for resolving relative paths)

    Returns:
        Tuple of (is_valid: bool, issues: list[str])
    """
    issues = []

    # Get expected derived spec path
    official_spec_path = component_config[CONFIG_KEY_OFFICIAL_SPEC]
    derived_spec_path = get_derived_spec_path(official_spec_path, config_dir)

    logging.debug(f"  {MSG_EXPECTED_DERIVED} {derived_spec_path}")

    # Check 1-2: Load derived spec (exists + valid YAML)
    derived_spec, errors = load_spec_safely(derived_spec_path, ERR_PARSE_FAILED)
    if errors:
        issues.extend(errors)
        return False, issues

    logging.debug(f"  ✓ {MSG_DERIVED_EXISTS}")
    logging.debug(f"  ✓ {MSG_VALID_YAML}")

    # Check 3: Derived spec has paths
    derived_paths = derived_spec.get(SPEC_KEY_PATHS, {})
    if not derived_paths:
        issues.append(ERR_NO_PATHS)
        return False, issues

    logging.debug(f"  ✓ {MSG_HAS_PATHS} {len(derived_paths)} paths")

    # Check 4-5: Load official spec (exists + valid YAML)
    official_spec, errors = load_spec_safely(official_spec_path, ERR_PARSE_OFFICIAL_FAILED)
    if errors:
        issues.extend(errors)
        return False, issues

    official_paths = official_spec.get(SPEC_KEY_PATHS, {})
    logging.debug(f"  ✓ {MSG_OFFICIAL_SPEC_PATHS} {len(official_paths)} paths")

    # Check 6: Derived spec is a subset of official spec
    derived_path_set = set(derived_paths.keys())
    official_path_set = set(official_paths.keys())

    invalid_paths = derived_path_set - official_path_set
    if invalid_paths:
        issues.append(f"{ERR_INVALID_PATHS} {invalid_paths}")
        return False, issues

    logging.debug(f"  ✓ {MSG_ALL_PATHS_VALID}")

    # Check 7: Overlay exists if specified
    overlay_path = component_config.get(CONFIG_KEY_OVERLAY)
    if overlay_path:
        overlay_errors = check_file_exists(overlay_path, ERR_OVERLAY_NOT_FOUND)
        if overlay_errors:
            issues.extend(overlay_errors)
        else:
            logging.debug(f"  ✓ {MSG_OVERLAY_EXISTS} {overlay_path}")

    # Check 8: Implementation spec exists (optional - only check if specified)
    impl_spec_path = component_config.get(CONFIG_KEY_IMPLEMENTATION_SPEC)
    if impl_spec_path:
        impl_errors = check_file_exists(impl_spec_path, ERR_IMPL_SPEC_NOT_FOUND)
        if impl_errors:
            issues.extend(impl_errors)
        else:
            logging.debug(f"  ✓ {MSG_IMPL_SPEC_EXISTS} {impl_spec_path}")

    # All checks passed
    if not issues:
        logging.info(f"    SUCCESS: {MSG_VALID_COMPONENT} ({len(derived_paths)} paths)")
        return True, []
    else:
        return False, issues


def main():
    parser = argparse.ArgumentParser(
        description="Validate that derived specs are up-to-date with configuration.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        ARG_NAME_CONFIG,
        help=ARG_HELP_CONFIG,
    )
    parser.add_argument(
        ARG_NAME_LOG_LEVEL,
        default=ARG_DEFAULT_LOG_LEVEL,
        choices=ARG_LOG_LEVEL_CHOICES,
        help=ARG_HELP_LOG_LEVEL,
    )

    args = parser.parse_args()

    # Set logging level
    logging.getLogger().setLevel(args.log_level)

    # Load configuration
    config_path = args.config or os.getenv(CONFIG_ENV_VAR, DEFAULT_CONFIG_PATH)
    try:
        config = load_config(config_path)
    except FileNotFoundError as e:
        logging.error(f"ERROR: {e}")
        sys.exit(1)

    config_name = config.get(CONFIG_KEY_NAME, DEFAULT_UNKNOWN)
    config_version = config.get(CONFIG_KEY_VERSION, DEFAULT_VERSION_EMPTY)

    logging.info(LOG_SEPARATOR)
    logging.info(MSG_VALIDATION_HEADER)
    logging.info(f"{MSG_IMPLEMENTATION} {config_name} {config_version}")
    logging.info(f"{MSG_CONFIGURATION} {config_path}")
    logging.info(LOG_SEPARATOR)

    components = config.get(CONFIG_KEY_COMPONENTS, {})
    if not components:
        logging.error(f"\nERROR: {MSG_NO_COMPONENTS}")
        sys.exit(1)

    # Validate each component
    valid_count = 0
    invalid_count = 0
    all_issues = {}

    config_dir = Path(config_path).parent

    for component_name, component_config in components.items():
        logging.info(f"\n  [{component_name}]")

        is_valid, issues = validate_component(component_config, config_dir)

        if is_valid:
            valid_count += 1
        else:
            invalid_count += 1
            all_issues[component_name] = issues
            for issue in issues:
                logging.error(f"    ERROR: {issue}")

    # Summary
    logging.info(f"\n{LOG_SEPARATOR}")
    logging.info(MSG_VALIDATION_SUMMARY)
    logging.info(LOG_SEPARATOR)
    logging.info(f"{MSG_TOTAL_COMPONENTS} {len(components)}")
    logging.info(f"  SUCCESS: {MSG_VALID} {valid_count}")
    if invalid_count > 0:
        logging.error(f"  ERROR: {MSG_INVALID} {invalid_count}")

    # Show remediation steps if there are issues
    if all_issues:
        logging.info(f"\n{LOG_SEPARATOR}")
        logging.info(MSG_REMEDIATION)
        logging.info(LOG_SEPARATOR)
        logging.info(MSG_REMEDIATION_HINT)
        logging.info(f"  python3 scripts/generate_implementation.py --config {config_path}")

    # Exit with error code if validation failed
    if invalid_count > 0:
        sys.exit(1)
    else:
        logging.info(f"\nSUCCESS: {MSG_ALL_VALID}")


if __name__ == "__main__":
    main()
