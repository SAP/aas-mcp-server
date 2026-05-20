# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for OpenAPI loader with path filtering and overlay support.

Run with: uv run pytest tests/test_openapi_loader.py -v
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

from aas_mcp_server.openapi_loader import (
    load_openapi_yaml,
    filter_paths,
    parse_path_filter,
    get_filter_paths_from_env,
    get_overlay_path,
    load_and_process_openapi,
    COMPONENT_FILTER_ENV_VARS,
)


# Path to test fixtures
OPENAPI_DIR = Path(__file__).parent.parent / "openapi"
AAS_REPO_SPEC = (
    OPENAPI_DIR
    / "AssetAdministrationShellRepositoryServiceSpecification-V3.1.1_SSP-001-resolved.yaml"
)
OVERLAYS_DIR = OPENAPI_DIR / "overlays"


class TestLoadOpenapiYaml:
    """Tests for load_openapi_yaml function."""

    def test_load_valid_yaml(self):
        """Test loading a valid OpenAPI YAML file."""
        if not AAS_REPO_SPEC.exists():
            pytest.skip(f"Test file not found: {AAS_REPO_SPEC}")

        spec = load_openapi_yaml(str(AAS_REPO_SPEC))

        assert spec is not None
        assert "openapi" in spec
        assert "paths" in spec
        assert "info" in spec

    def test_load_nonexistent_file(self):
        """Test loading a non-existent file raises error."""
        with pytest.raises(FileNotFoundError):
            load_openapi_yaml("nonexistent.yaml")


class TestParsePathFilter:
    """Tests for parse_path_filter function."""

    def test_parse_path_only(self):
        """Test parsing path without methods."""
        path, methods = parse_path_filter("/shells")
        assert path == "/shells"
        assert methods is None

    def test_parse_path_with_single_method(self):
        """Test parsing path with single method."""
        path, methods = parse_path_filter("/shells:get")
        assert path == "/shells"
        assert methods == ["get"]

    def test_parse_path_with_multiple_methods(self):
        """Test parsing path with multiple methods."""
        path, methods = parse_path_filter("/shells:get,post,delete")
        assert path == "/shells"
        assert methods == ["get", "post", "delete"]

    def test_parse_path_with_uppercase_methods(self):
        """Test that methods are lowercased."""
        path, methods = parse_path_filter("/shells:GET,POST")
        assert path == "/shells"
        assert methods == ["get", "post"]

    def test_parse_path_with_whitespace(self):
        """Test that whitespace is stripped from methods."""
        path, methods = parse_path_filter("/shells:get , post , delete")
        assert path == "/shells"
        assert methods == ["get", "post", "delete"]


class TestFilterPaths:
    """Tests for filter_paths function."""

    def test_filter_single_path_all_methods(self):
        """Test filtering to a single path with all methods."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/shells": {"get": {}, "post": {}},
                "/shells/{id}": {"get": {}, "delete": {}},
                "/submodels": {"get": {}},
            },
        }

        result = filter_paths(spec, ["/shells"])

        assert len(result["paths"]) == 1
        assert "/shells" in result["paths"]
        assert "get" in result["paths"]["/shells"]
        assert "post" in result["paths"]["/shells"]

    def test_filter_single_path_single_method(self):
        """Test filtering to a single path with single method."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/shells": {"get": {}, "post": {}, "delete": {}},
            },
        }

        result = filter_paths(spec, ["/shells:get"])

        assert len(result["paths"]) == 1
        assert "get" in result["paths"]["/shells"]
        assert "post" not in result["paths"]["/shells"]
        assert "delete" not in result["paths"]["/shells"]

    def test_filter_single_path_multiple_methods(self):
        """Test filtering to a single path with multiple methods."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/shells": {"get": {}, "post": {}, "delete": {}, "put": {}},
            },
        }

        result = filter_paths(spec, ["/shells:get,post"])

        assert len(result["paths"]) == 1
        assert "get" in result["paths"]["/shells"]
        assert "post" in result["paths"]["/shells"]
        assert "delete" not in result["paths"]["/shells"]
        assert "put" not in result["paths"]["/shells"]

    def test_filter_multiple_paths_different_methods(self):
        """Test filtering multiple paths with different methods."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/shells": {"get": {}, "post": {}},
                "/shells/{id}": {"get": {}, "put": {}, "delete": {}},
                "/submodels": {"get": {}},
            },
        }

        result = filter_paths(spec, ["/shells:get", "/shells/{id}:get,delete"])

        assert len(result["paths"]) == 2
        assert "get" in result["paths"]["/shells"]
        assert "post" not in result["paths"]["/shells"]
        assert "get" in result["paths"]["/shells/{id}"]
        assert "delete" in result["paths"]["/shells/{id}"]
        assert "put" not in result["paths"]["/shells/{id}"]

    def test_filter_preserves_non_method_properties(self):
        """Test that filtering preserves non-method properties like parameters."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/shells": {
                    "parameters": [{"name": "limit", "in": "query"}],
                    "get": {"operationId": "getShells"},
                    "post": {"operationId": "createShell"},
                },
            },
        }

        result = filter_paths(spec, ["/shells:get"])

        assert "parameters" in result["paths"]["/shells"]
        assert "get" in result["paths"]["/shells"]
        assert "post" not in result["paths"]["/shells"]

    def test_filter_multiple_paths(self):
        """Test filtering to multiple paths."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/shells": {"get": {}},
                "/shells/{id}": {"get": {}},
                "/submodels": {"get": {}},
                "/submodels/{id}": {"get": {}},
            },
        }

        result = filter_paths(spec, ["/shells", "/shells/{id}"])

        assert len(result["paths"]) == 2
        assert "/shells" in result["paths"]
        assert "/shells/{id}" in result["paths"]
        assert "/submodels" not in result["paths"]

    def test_filter_preserves_operations(self):
        """Test that filtering preserves path operations."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/shells": {
                    "get": {"operationId": "getShells"},
                    "post": {"operationId": "createShell"},
                },
            },
        }

        result = filter_paths(spec, ["/shells"])

        assert result["paths"]["/shells"]["get"]["operationId"] == "getShells"
        assert result["paths"]["/shells"]["post"]["operationId"] == "createShell"

    def test_filter_empty_include_list(self):
        """Test filtering with empty include list."""
        spec = {"openapi": "3.0.0", "paths": {"/shells": {"get": {}}}}

        result = filter_paths(spec, [])

        assert len(result["paths"]) == 0

    def test_filter_does_not_modify_original(self):
        """Test that filtering does not modify the original spec."""
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/shells": {"get": {}},
                "/submodels": {"get": {}},
            },
        }

        filter_paths(spec, ["/shells"])

        assert len(spec["paths"]) == 2  # Original unchanged


class TestGetFilterPathsFromEnv:
    """Tests for get_filter_paths_from_env function."""

    def test_get_paths_from_env(self):
        """Test getting filter paths from environment variable."""
        with patch.dict(os.environ, {"AAS_REPO_FILTER_PATHS": "/shells;/shells/{id}"}):
            paths = get_filter_paths_from_env("aas-repo")

        assert paths == ["/shells", "/shells/{id}"]

    def test_get_paths_with_methods(self):
        """Test getting filter paths with methods from environment variable."""
        with patch.dict(
            os.environ, {"AAS_REPO_FILTER_PATHS": "/shells:get,post;/shells/{id}:get"}
        ):
            paths = get_filter_paths_from_env("aas-repo")

        assert paths == ["/shells:get,post", "/shells/{id}:get"]

    def test_get_paths_with_whitespace(self):
        """Test that whitespace is stripped from paths."""
        with patch.dict(
            os.environ, {"AAS_REPO_FILTER_PATHS": " /shells ; /shells/{id} "}
        ):
            paths = get_filter_paths_from_env("aas-repo")

        assert paths == ["/shells", "/shells/{id}"]

    def test_returns_none_when_env_not_set(self):
        """Test returns None when environment variable is not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Ensure the env var is not set
            os.environ.pop("AAS_REPO_FILTER_PATHS", None)
            paths = get_filter_paths_from_env("aas-repo")

        assert paths is None

    def test_returns_none_for_unknown_component(self):
        """Test returns None for unknown component."""
        paths = get_filter_paths_from_env("unknown-component")

        assert paths is None

    def test_all_components_have_env_vars(self):
        """Test that all components have environment variable mappings."""
        expected_components = [
            "aas-repo",
            "submodel-repo",
            "aas-registry",
            "submodel-registry",
        ]

        for component in expected_components:
            assert component in COMPONENT_FILTER_ENV_VARS


class TestGetOverlayPath:
    """Tests for get_overlay_path function."""

    def test_returns_path_when_overlay_exists(self):
        """Test returns path when overlay file exists."""
        overlay_path = get_overlay_path("aas-repo", str(OVERLAYS_DIR))

        if (OVERLAYS_DIR / "aas-repo-overlay.yaml").exists():
            assert overlay_path is not None
            assert overlay_path.name == "aas-repo-overlay.yaml"
        else:
            assert overlay_path is None

    def test_returns_none_when_overlay_missing(self):
        """Test returns None when overlay file does not exist."""
        overlay_path = get_overlay_path("nonexistent-component", str(OVERLAYS_DIR))

        assert overlay_path is None


class TestLoadAndProcessOpenapi:
    """Integration tests for load_and_process_openapi function."""

    @pytest.fixture
    def cleanup_env(self):
        """Clean up environment variables after test."""
        yield
        os.environ.pop("AAS_REPO_FILTER_PATHS", None)

    def test_load_without_filter_or_overlay(self, cleanup_env):
        """Test loading spec without filtering or overlay."""
        if not AAS_REPO_SPEC.exists():
            pytest.skip(f"Test file not found: {AAS_REPO_SPEC}")

        spec = load_and_process_openapi(
            str(AAS_REPO_SPEC), "aas-repo", overlay_base_dir="nonexistent-dir"
        )

        assert spec is not None
        assert len(spec["paths"]) > 10  # Full spec has many paths

    def test_load_with_filter_only(self, cleanup_env):
        """Test loading spec with path filtering only."""
        if not AAS_REPO_SPEC.exists():
            pytest.skip(f"Test file not found: {AAS_REPO_SPEC}")

        os.environ["AAS_REPO_FILTER_PATHS"] = "/shells"

        spec = load_and_process_openapi(
            str(AAS_REPO_SPEC), "aas-repo", overlay_base_dir="nonexistent-dir"
        )

        assert len(spec["paths"]) == 1
        assert "/shells" in spec["paths"]

    def test_load_with_overlay_only(self, cleanup_env):
        """Test loading spec with overlay only (no filtering)."""
        if not AAS_REPO_SPEC.exists():
            pytest.skip(f"Test file not found: {AAS_REPO_SPEC}")
        if not (OVERLAYS_DIR / "aas-repo-overlay.yaml").exists():
            pytest.skip("Overlay file not found")

        spec = load_and_process_openapi(
            str(AAS_REPO_SPEC), "aas-repo", overlay_base_dir=str(OVERLAYS_DIR)
        )

        # Check overlay was applied - operationId should be changed
        assert spec["paths"]["/shells"]["get"]["operationId"] == "list_shells"
        assert spec["paths"]["/shells"]["post"]["operationId"] == "create_shell"

    def test_load_with_filter_and_overlay(self, cleanup_env):
        """Test loading spec with both filtering and overlay."""
        if not AAS_REPO_SPEC.exists():
            pytest.skip(f"Test file not found: {AAS_REPO_SPEC}")
        if not (OVERLAYS_DIR / "aas-repo-overlay.yaml").exists():
            pytest.skip("Overlay file not found")

        os.environ["AAS_REPO_FILTER_PATHS"] = "/shells"

        spec = load_and_process_openapi(
            str(AAS_REPO_SPEC), "aas-repo", overlay_base_dir=str(OVERLAYS_DIR)
        )

        # Check filtering was applied
        assert len(spec["paths"]) == 1
        assert "/shells" in spec["paths"]

        # Check overlay was applied
        assert spec["paths"]["/shells"]["get"]["operationId"] == "list_shells"
        assert spec["paths"]["/shells"]["post"]["operationId"] == "create_shell"
        assert (
            spec["paths"]["/shells"]["get"]["summary"]
            == "List all Asset Administration Shells"
        )

    def test_filter_multiple_paths_with_overlay(self, cleanup_env):
        """Test filtering multiple paths and applying overlay."""
        if not AAS_REPO_SPEC.exists():
            pytest.skip(f"Test file not found: {AAS_REPO_SPEC}")

        os.environ["AAS_REPO_FILTER_PATHS"] = "/shells;/shells/{aasIdentifier}"

        spec = load_and_process_openapi(
            str(AAS_REPO_SPEC), "aas-repo", overlay_base_dir=str(OVERLAYS_DIR)
        )

        assert len(spec["paths"]) == 2
        assert "/shells" in spec["paths"]
        assert "/shells/{aasIdentifier}" in spec["paths"]


class TestOverlayContent:
    """Tests to verify overlay content is applied correctly."""

    @pytest.fixture
    def cleanup_env(self):
        """Clean up environment variables after test."""
        yield
        os.environ.pop("AAS_REPO_FILTER_PATHS", None)

    def test_overlay_changes_operation_id(self, cleanup_env):
        """Test that overlay correctly changes operationId."""
        if not AAS_REPO_SPEC.exists():
            pytest.skip(f"Test file not found: {AAS_REPO_SPEC}")
        if not (OVERLAYS_DIR / "aas-repo-overlay.yaml").exists():
            pytest.skip("Overlay file not found")

        os.environ["AAS_REPO_FILTER_PATHS"] = "/shells"

        spec = load_and_process_openapi(
            str(AAS_REPO_SPEC), "aas-repo", overlay_base_dir=str(OVERLAYS_DIR)
        )

        # Verify GET /shells operationId
        get_operation = spec["paths"]["/shells"]["get"]
        assert get_operation["operationId"] == "list_shells"

        # Verify POST /shells operationId
        post_operation = spec["paths"]["/shells"]["post"]
        assert post_operation["operationId"] == "create_shell"

    def test_overlay_changes_summary(self, cleanup_env):
        """Test that overlay correctly changes summary."""
        if not AAS_REPO_SPEC.exists():
            pytest.skip(f"Test file not found: {AAS_REPO_SPEC}")
        if not (OVERLAYS_DIR / "aas-repo-overlay.yaml").exists():
            pytest.skip("Overlay file not found")

        os.environ["AAS_REPO_FILTER_PATHS"] = "/shells"

        spec = load_and_process_openapi(
            str(AAS_REPO_SPEC), "aas-repo", overlay_base_dir=str(OVERLAYS_DIR)
        )

        # Verify summaries were updated
        assert (
            spec["paths"]["/shells"]["get"]["summary"]
            == "List all Asset Administration Shells"
        )
        assert (
            spec["paths"]["/shells"]["post"]["summary"]
            == "Create a new Asset Administration Shell"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
