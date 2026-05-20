# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Spec processor for AAS MCP Server.

This module handles loading and deriving OpenAPI specifications based on configuration.
It implements the smart derivation logic:
- If both official + implementation specs exist: derive intersection + apply overlay
- If only implementation spec: use it + apply overlay
- If only official spec: use it + apply overlay
"""

import logging
from pathlib import Path
from typing import Any, Dict
import yaml
from oas_patch import apply_overlay

from .config import ComponentConfig
from .constants import VALID_HTTP_METHODS


logger = logging.getLogger(__name__)


def load_yaml(path: Path) -> Dict[str, Any]:
    """Load YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def derive_spec_from_intersection(
    official_spec: Dict[str, Any], implementation_spec: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Derive OpenAPI spec from intersection of official and implementation specs.

    Only includes paths and methods that exist in BOTH specs.

    Args:
        official_spec: Official AAS OpenAPI specification
        implementation_spec: Implementation-specific spec defining supported endpoints

    Returns:
        Derived spec containing only paths/methods in both specs
    """
    derived = official_spec.copy()

    official_paths = official_spec.get("paths", {})
    impl_paths = implementation_spec.get("paths", {})

    logger.debug(f"Official spec paths ({len(official_paths)}):")
    for path in sorted(official_paths.keys()):
        methods = [m for m in official_paths[path].keys() if m in VALID_HTTP_METHODS]
        logger.debug(f"  {path}: {methods}")

    logger.debug(f"Implementation spec paths ({len(impl_paths)}):")
    for path in sorted(impl_paths.keys()):
        methods = [m for m in impl_paths[path].keys() if m in VALID_HTTP_METHODS]
        logger.debug(f"  {path}: {methods}")

    # Filter to paths that exist in both specs
    filtered_paths = {}

    for path, operations in official_paths.items():
        if path not in impl_paths:
            logger.debug(f"Path {path} not in implementation spec - skipping")
            continue

        impl_operations = impl_paths[path]
        filtered_operations = {}

        # For each HTTP method in official spec
        for method, operation_def in operations.items():
            # Skip non-method fields (parameters, servers, etc.)
            if method not in VALID_HTTP_METHODS:
                # Keep non-method fields
                filtered_operations[method] = operation_def
                continue

            # Only include if method exists in implementation spec
            if method in impl_operations:
                filtered_operations[method] = operation_def
                logger.debug(f"Matched: {method.upper()} {path}")
            else:
                logger.debug(f"Method {method} not in implementation for path {path}")

        # Only include path if it has at least one method
        has_methods = any(
            key in VALID_HTTP_METHODS for key in filtered_operations.keys()
        )
        if has_methods:
            filtered_paths[path] = filtered_operations

    derived["paths"] = filtered_paths

    logger.info(
        f"Derived spec: {len(filtered_paths)} paths "
        f"(from {len(official_paths)} official paths, {len(impl_paths)} implementation paths)"
    )

    return derived


def process_component_spec(component_config: ComponentConfig) -> Dict[str, Any]:
    """
    Process component specification according to smart derivation logic.

    Logic:
    1. If both official + implementation specs: derive intersection
    2. If only implementation spec: use it directly
    3. If only official spec: use it directly
    4. Apply overlay if it exists (optional)

    Args:
        component_config: Component configuration

    Returns:
        Processed OpenAPI specification ready for MCP tool generation
    """
    logger.info(f"Processing spec for component: {component_config.component_name}")

    # Case 1: Both specs provided - derive intersection
    if component_config.has_both_specs():
        logger.info(
            "Both official and implementation specs provided - deriving intersection"
        )

        official = load_yaml(component_config.official_spec)
        implementation = load_yaml(component_config.implementation_spec)

        spec = derive_spec_from_intersection(official, implementation)

    # Case 2: Only implementation spec
    elif component_config.implementation_spec:
        logger.info("Only implementation spec provided - using directly")
        spec = load_yaml(component_config.implementation_spec)

    # Case 3: Only official spec
    else:
        logger.info("Only official spec provided - using directly")
        spec = load_yaml(component_config.official_spec)

    # Apply overlay if it exists (optional step)
    if component_config.overlay:
        logger.info(f"Applying overlay: {component_config.overlay}")
        try:
            overlay = load_yaml(component_config.overlay)
            spec = apply_overlay(spec, overlay)
            logger.info("Overlay applied successfully")
        except Exception as e:
            logger.warning(f"Failed to apply overlay: {e}")
            # Continue without overlay - it's optional

    # Log summary
    path_count = len(spec.get("paths", {}))
    logger.info(f"Final spec has {path_count} paths")

    return spec
