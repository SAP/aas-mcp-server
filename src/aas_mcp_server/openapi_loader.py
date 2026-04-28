# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
OpenAPI spec loader with support for path filtering and overlay application.

Environment Variables (per component):
    AAS_REPO_FILTER_PATHS: Semicolon-separated list of path filters for aas-repo
    SUBMODEL_REPO_FILTER_PATHS: Semicolon-separated list of path filters for submodel-repo
    AAS_REGISTRY_FILTER_PATHS: Semicolon-separated list of path filters for aas-registry
    SUBMODEL_REGISTRY_FILTER_PATHS: Semicolon-separated list of path filters for submodel-registry

Path Filter Format:
    - "/path" - include all HTTP methods for this path
    - "/path:get" - include only GET method
    - "/path:get,post" - include GET and POST methods
    - Use semicolon (;) to separate multiple path filters

    Examples:
        AAS_REPO_FILTER_PATHS="/shells:get,post;/shells/{aasIdentifier}:get,put,delete"

Overlay files are expected at: {overlay_base_dir}/{component}-overlay.yaml
The overlay_base_dir is provided via configuration or function arguments.
"""

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from oas_patch import apply_overlay

from .constants import (
    FILTER_DELIMITER,
    METHOD_SEPARATOR,
    PATH_FILTER_SEPARATOR,
    FILE_ENCODING,
    VALID_HTTP_METHODS,
    OPENAPI_KEY_PATHS,
    OVERLAY_FILE_PATTERN,
    COMPONENT_FILTER_ENV_VARS,
)

# HTTP_METHODS alias for backward compatibility in this module
HTTP_METHODS = VALID_HTTP_METHODS


def load_openapi_yaml(path: str) -> dict[str, Any]:
    """
    Load an OpenAPI YAML file.

    If the path is relative, it's resolved by checking multiple locations:
    1. Current working directory (for Docker, usually /app)
    2. Project root (parent of parent of package dir, for local development)
    """
    path_obj = Path(path)

    # If path is absolute, use it directly
    if path_obj.is_absolute():
        with open(path_obj, "r", encoding=FILE_ENCODING) as f:
            return yaml.safe_load(f)

    # Try multiple locations for relative paths
    locations_to_try = [
        # 1. Current working directory (works in Docker when WORKDIR is /app)
        Path.cwd() / path,
        # 2. Project root (works in local development)
        Path(__file__).parent.parent.parent / path,
    ]

    for location in locations_to_try:
        if location.exists():
            with open(location, "r", encoding=FILE_ENCODING) as f:
                return yaml.safe_load(f)

    # If not found, raise error with helpful message
    tried_paths = "\n  - ".join(str(loc) for loc in locations_to_try)
    raise FileNotFoundError(
        f"OpenAPI spec not found: {path}\n"
        f"Tried locations:\n  - {tried_paths}"
    )


def parse_path_filter(filter_str: str) -> tuple[str, list[str] | None]:
    """
    Parse a path filter string into path and methods.

    Format: "/path:method1,method2" or "/path" (all methods)

    Examples:
        "/shells:get,post" -> ("/shells", ["get", "post"])
        "/shells:get" -> ("/shells", ["get"])
        "/shells" -> ("/shells", None)  # None means all methods

    Args:
        filter_str: Filter string like "/shells:get,post" or "/shells"

    Returns:
        Tuple of (path, methods) where methods is None for all methods
    """
    if FILTER_DELIMITER in filter_str:
        path, methods_str = filter_str.rsplit(FILTER_DELIMITER, 1)
        methods = [m.strip().lower() for m in methods_str.split(METHOD_SEPARATOR) if m.strip()]
        return path, methods if methods else None
    return filter_str, None


def _build_path_methods_map(include_filters: list[str]) -> dict[str, set[str] | None]:
    """
    Build a mapping of paths to their allowed methods from filter strings.

    Args:
        include_filters: List of path filter strings

    Returns:
        Dict mapping path to set of methods (or None for all methods)
    """
    path_methods: dict[str, set[str] | None] = {}

    for filter_str in include_filters:
        path, methods = parse_path_filter(filter_str)

        if path not in path_methods:
            path_methods[path] = set(methods) if methods else None
        elif methods is None:
            # If any filter says "all methods", use all methods
            path_methods[path] = None
        elif path_methods[path] is not None:
            # Merge methods if both specify methods
            path_methods[path].update(methods)

    return path_methods


def _filter_path_definition(
    definition: dict[str, Any],
    allowed_methods: set[str] | None,
    http_methods: set[str]
) -> dict[str, Any] | None:
    """
    Filter a path definition to include only allowed methods.

    Args:
        definition: Path definition from OpenAPI spec
        allowed_methods: Set of allowed methods (None = all methods)
        http_methods: Set of valid HTTP method names

    Returns:
        Filtered definition, or None if no methods remain
    """
    if allowed_methods is None:
        # Include all methods
        return definition

    # Include only specified methods
    filtered_definition = {
        key: value
        for key, value in definition.items()
        if key.lower() not in http_methods or key.lower() in allowed_methods
    }

    # Only return if at least one HTTP method remains
    if any(k.lower() in http_methods for k in filtered_definition):
        return filtered_definition

    return None


def filter_paths(spec: dict[str, Any], include_filters: list[str]) -> dict[str, Any]:
    """
    Filter OpenAPI spec to include only specified paths and methods.

    Args:
        spec: The OpenAPI specification dict
        include_filters: List of path filters to keep
            Format: "/path:method1,method2" or "/path" (all methods)
            Examples:
                - "/shells" - include all methods for /shells
                - "/shells:get" - include only GET /shells
                - "/shells:get,post" - include GET and POST /shells

    Returns:
        A new spec with only the specified paths and methods
    """
    result = deepcopy(spec)

    # Parse all filters into a dict: {path: set of methods or None}
    path_methods = _build_path_methods_map(include_filters)

    # Filter paths and methods
    filtered_paths = {}

    for path, definition in spec.get(OPENAPI_KEY_PATHS, {}).items():
        if path not in path_methods:
            continue

        allowed_methods = path_methods[path]
        filtered_definition = _filter_path_definition(definition, allowed_methods, HTTP_METHODS)

        if filtered_definition is not None:
            filtered_paths[path] = filtered_definition

    result[OPENAPI_KEY_PATHS] = filtered_paths
    return result


def get_overlay_path(component_name: str, base_dir: str) -> Path | None:
    """
    Get the overlay file path for a component if it exists.

    Checks multiple locations for the overlay directory.

    Args:
        component_name: Name of the component (e.g., 'aas-repo')
        base_dir: Base directory for overlay files (required)

    Returns:
        Path to overlay file if it exists, None otherwise
    """
    base_path = Path(base_dir)

    # Try multiple locations for relative paths
    if not base_path.is_absolute():
        locations_to_try = [
            # 1. Current working directory (Docker)
            Path.cwd() / base_dir,
            # 2. Project root (local development)
            Path(__file__).parent.parent.parent / base_dir,
        ]
    else:
        locations_to_try = [base_path]

    overlay_filename = OVERLAY_FILE_PATTERN.format(component_name=component_name)

    for location in locations_to_try:
        overlay_path = location / overlay_filename
        if overlay_path.exists():
            return overlay_path

    return None


def get_filter_paths_from_env(component_name: str) -> list[str] | None:
    """
    Get filter paths from environment variable for a component.

    Args:
        component_name: Name of the component (e.g., 'aas-repo')

    Returns:
        List of path filters to include, or None if not set
    """
    env_var = COMPONENT_FILTER_ENV_VARS.get(component_name)
    if not env_var:
        return None

    paths_str = os.getenv(env_var)
    if not paths_str:
        return None

    # Parse semicolon-separated path filters, strip whitespace
    return [p.strip() for p in paths_str.split(PATH_FILTER_SEPARATOR) if p.strip()]


def load_and_process_openapi(
    openapi_path: str,
    component_name: str,
    overlay_base_dir: str | None = None,
) -> dict[str, Any]:
    """
    Load OpenAPI spec with optional filtering and overlay application.

    Processing order:
    1. Load the original OpenAPI spec
    2. If filter paths env var is set for this component, filter to those paths
    3. If overlay file exists for this component, apply the overlay

    Args:
        openapi_path: Path to the OpenAPI spec file
        component_name: Name of the component (e.g., 'aas-repo')
        overlay_base_dir: Base directory for overlay files (optional, no overlay if not provided)

    Returns:
        Processed OpenAPI specification dict
    """
    # Step 1: Load original spec
    spec = load_openapi_yaml(openapi_path)

    # Step 2: Apply path filtering if env var is set
    filter_paths_list = get_filter_paths_from_env(component_name)
    if filter_paths_list:
        spec = filter_paths(spec, filter_paths_list)

    # Step 3: Apply overlay if base_dir is provided and overlay exists
    if overlay_base_dir:
        overlay_path = get_overlay_path(component_name, overlay_base_dir)
        if overlay_path:
            overlay = load_openapi_yaml(str(overlay_path))
            spec = apply_overlay(spec, overlay)

    return spec
