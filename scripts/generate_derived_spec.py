# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Library for generating derived OpenAPI specs with path filtering and overlay applied.

This module is used by generate_implementation.py to generate derived specs.
It can also be imported and used programmatically for custom workflows.

Path Filter Format:
    - "/path" - include all HTTP methods for this path
    - "/path:get" - include only GET method
    - "/path:get,post" - include GET and POST methods
    - Use semicolon (;) to separate multiple path filters
"""

import logging
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import yaml
from aas_mcp_server.openapi_loader import (
    load_openapi_yaml,
    filter_paths,
)
from aas_mcp_server.constants import COMPONENT_FILTER_ENV_VARS
from oas_patch import apply_overlay

# Set up logger
logger = logging.getLogger(__name__)

# Constants
OPENAPI_DIR = "openapi"
OVERLAYS_DIR = f"{OPENAPI_DIR}/overlays"
DERIVED_DIR = f"{OPENAPI_DIR}/derived"
OVERLAY_FILENAME_SUFFIX = "-overlay.yaml"
DERIVED_FILENAME_SUFFIX = "-derived.yaml"
FILTER_PATH_SEPARATOR = ";"
SPEC_KEY_PATHS = "paths"
SPEC_KEY_OPERATION_ID = "operationId"
HTTP_METHODS = ["get", "post", "put", "patch", "delete"]
DEFAULT_OPERATION_ID = "N/A"
LOG_SEPARATOR = "=" * 60
LOG_STEP_PREFIX_1 = "[1/3]"
LOG_STEP_PREFIX_2 = "[2/3]"
LOG_STEP_PREFIX_3 = "[3/3]"
LOG_INDENT = "      "

# Component to OpenAPI spec mapping (for build-time convenience when spec_path is not provided)
# These paths are relative to project root and used as defaults during spec generation.
# At runtime, the MCP server loads specs via config.yaml instead.
COMPONENT_SPECS = {
    "aas-repo": f"{OPENAPI_DIR}/AssetAdministrationShellRepositoryServiceSpecification-V3.1.1_SSP-001-resolved.yaml",
    "submodel-repo": f"{OPENAPI_DIR}/SubmodelRepositoryServiceSpecification-V3.1.1_SSP-001-resolved.yaml",
    "aas-registry": f"{OPENAPI_DIR}/AssetAdministrationShellRegistryServiceSpecification-V3.1.1_SSP-001-resolved.yaml",
    "submodel-registry": f"{OPENAPI_DIR}/SubmodelRegistryServiceSpecification-V3.1.1_SSP-001-resolved.yaml",
}


def _resolve_spec_path(component: str, spec_path: Optional[str]) -> Path:
    """Resolve the OpenAPI spec path for a component."""
    if component not in COMPONENT_SPECS:
        raise ValueError(f"Unknown component: {component}. Valid: {list(COMPONENT_SPECS.keys())}")

    resolved_path = Path(spec_path or COMPONENT_SPECS[component])
    if not resolved_path.exists():
        raise FileNotFoundError(f"Source spec not found: {resolved_path}")

    return resolved_path


def _resolve_filter_paths(component: str, filter_paths_list: Optional[List[str]]) -> Optional[List[str]]:
    """Resolve filter paths from parameter or environment variable."""
    if filter_paths_list is not None:
        return filter_paths_list

    env_var = COMPONENT_FILTER_ENV_VARS.get(component)
    if env_var and os.getenv(env_var):
        return [p.strip() for p in os.getenv(env_var).split(FILTER_PATH_SEPARATOR) if p.strip()]

    return None


def _resolve_overlay_path(component: str, overlay_path: Optional[Path]) -> Optional[Path]:
    """Resolve overlay path from parameter or default location."""
    if overlay_path is not None:
        return overlay_path

    default_overlay = Path(f"{OVERLAYS_DIR}/{component}{OVERLAY_FILENAME_SUFFIX}")
    return default_overlay if default_overlay.exists() else None


def _resolve_output_path(spec_file: Path, output_path: Optional[Path]) -> Path:
    """Resolve output path from parameter or generate default."""
    if output_path is not None:
        return output_path

    original_filename = spec_file.stem
    return Path(f"{DERIVED_DIR}/{original_filename}{DERIVED_FILENAME_SUFFIX}")


def _log_configuration(component: str, spec_path: Path, filter_paths_list: Optional[List[str]],
                       overlay_path: Optional[Path], output_path: Path) -> None:
    """Log the configuration for spec generation."""
    logger.info(LOG_SEPARATOR)
    logger.info("Configuration:")
    logger.info(f"  Component:     {component}")
    logger.info(f"  Source spec:   {spec_path}")
    logger.info(f"  Filter paths:  {filter_paths_list or 'None (full spec)'}")
    logger.info(f"  Overlay:       {overlay_path or 'None'}")
    logger.info(f"  Output:        {output_path}")
    logger.info(LOG_SEPARATOR)


def _load_spec(spec_path: Path, verbose: bool) -> Dict[str, Any]:
    """Load OpenAPI spec with optional logging."""
    if verbose:
        logger.info(f"\n{LOG_STEP_PREFIX_1} Loading source spec...")

    spec = load_openapi_yaml(str(spec_path))

    if verbose:
        logger.info(f"{LOG_INDENT}Loaded {len(spec.get(SPEC_KEY_PATHS, {}))} paths")

    return spec


def _apply_filters(spec: Dict[str, Any], filter_paths_list: Optional[List[str]],
                   verbose: bool) -> Dict[str, Any]:
    """Apply path filters with optional logging."""
    if not filter_paths_list:
        if verbose:
            logger.info(f"\n{LOG_STEP_PREFIX_2} Skipping filtering (no filter paths specified)")
        return spec

    if verbose:
        logger.info(f"\n{LOG_STEP_PREFIX_2} Filtering to {len(filter_paths_list)} paths...")

    filtered_spec = filter_paths(spec, filter_paths_list)

    if verbose:
        logger.info(f"{LOG_INDENT}Remaining paths: {list(filtered_spec[SPEC_KEY_PATHS].keys())}")

    return filtered_spec


def _apply_overlay(spec: Dict[str, Any], overlay_path: Optional[Path],
                   verbose: bool) -> Dict[str, Any]:
    """Apply overlay with optional logging."""
    if not overlay_path or not overlay_path.exists():
        if verbose:
            logger.info(f"\n{LOG_STEP_PREFIX_3} Skipping overlay (no overlay file)")
        return spec

    if verbose:
        logger.info(f"\n{LOG_STEP_PREFIX_3} Applying overlay from {overlay_path}...")

    overlay = load_openapi_yaml(str(overlay_path))
    overlaid_spec = apply_overlay(spec, overlay)

    if verbose:
        logger.info(f"{LOG_INDENT}Overlay applied successfully")

    return overlaid_spec


def _write_spec(spec: Dict[str, Any], output_path: Path) -> None:
    """Write spec to output file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(spec, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _log_summary(spec: Dict[str, Any], output_path: Path) -> None:
    """Log summary of generated spec."""
    logger.info(f"\nDerived spec written to: {output_path}")
    logger.info(f"   Paths in derived spec: {len(spec.get(SPEC_KEY_PATHS, {}))}")

    logger.info("\nSummary of derived spec:")
    for path, operations in spec.get(SPEC_KEY_PATHS, {}).items():
        methods = [m.upper() for m in operations.keys() if m in HTTP_METHODS]
        op_ids = [
            operations[m.lower()].get(SPEC_KEY_OPERATION_ID, DEFAULT_OPERATION_ID)
            for m in methods
            if m.lower() in operations
        ]
        logger.info(f"   {path}")
        for method, op_id in zip(methods, op_ids):
            logger.info(f"{LOG_INDENT}{method}: {op_id}")


def generate_derived_spec(
    component: str,
    filter_paths_list: Optional[List[str]] = None,
    overlay_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    spec_path: Optional[str] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Generate a derived OpenAPI spec with filtering and overlay applied.

    Args:
        component: Component name (e.g., "aas-repo", "submodel-repo")
        filter_paths_list: List of path filters (e.g., ["/shells:get,post", "/shells/{aasIdentifier}:get"])
                          If None, uses environment variable for the component
        overlay_path: Path to overlay YAML file. If None, uses default overlay for component
        output_path: Output file path. If None, uses default: openapi/derived/{component}-derived.yaml
        spec_path: Path to source OpenAPI spec. If None, uses default for component
        verbose: Print progress messages

    Returns:
        The generated OpenAPI spec as a dictionary

    Raises:
        FileNotFoundError: If source spec file doesn't exist
        ValueError: If component is not recognized
    """
    # Resolve all paths and parameters
    resolved_spec_path = _resolve_spec_path(component, spec_path)
    resolved_filter_paths = _resolve_filter_paths(component, filter_paths_list)
    resolved_overlay_path = _resolve_overlay_path(component, overlay_path)
    resolved_output_path = _resolve_output_path(resolved_spec_path, output_path)

    # Log configuration
    if verbose:
        _log_configuration(component, resolved_spec_path, resolved_filter_paths,
                          resolved_overlay_path, resolved_output_path)

    # Process spec through pipeline
    spec = _load_spec(resolved_spec_path, verbose)
    spec = _apply_filters(spec, resolved_filter_paths, verbose)
    spec = _apply_overlay(spec, resolved_overlay_path, verbose)

    # Write output
    _write_spec(spec, resolved_output_path)

    # Log summary
    if verbose:
        _log_summary(spec, resolved_output_path)

    return spec
