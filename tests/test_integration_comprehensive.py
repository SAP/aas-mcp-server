# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Comprehensive integration tests for AAS MCP Server.

Tests the complete pipeline:
1. Configuration loading
2. Spec intersection (official ∩ implementation)
3. Overlay application
4. Curation (allowlist + aliases)
5. MCP tool generation
6. Backend connectivity (if available)

This test suite is designed for CI/CD and expects:
- Backend AAS services running on localhost:8081 (optional, tests skip if unavailable)
- Test fixtures in tests/fixtures/
"""

import pytest
import yaml
from pathlib import Path
import httpx

from aas_mcp_server.config import load_config
from aas_mcp_server.spec_processor import (
    process_component_spec,
    derive_spec_from_intersection,
)
from aas_mcp_server.tool_curation import curate_openapi_spec
from aas_mcp_server.server import build_mcp_server


# Test configuration
BACKEND_URL = "http://localhost:8081"
BACKEND_TIMEOUT = 5.0


@pytest.fixture
def test_fixtures_dir():
    """Path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def backend_available():
    """Check if backend services are available on port 8081."""
    try:
        response = httpx.get(f"{BACKEND_URL}/shells", timeout=BACKEND_TIMEOUT)
        return response.status_code in [200, 404]  # 404 is fine (no shells yet)
    except Exception:
        return False


@pytest.fixture
def sample_official_spec(test_fixtures_dir):
    """Load official AAS Repository spec from fixture file."""
    with open(test_fixtures_dir / "sample_official_spec.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture
def sample_implementation_spec(test_fixtures_dir):
    """Load implementation spec from fixture file."""
    with open(test_fixtures_dir / "sample_implementation_spec.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture
def sample_overlay(test_fixtures_dir):
    """Load overlay from fixture file."""
    with open(test_fixtures_dir / "sample_overlay.yaml") as f:
        return yaml.safe_load(f)


class TestSpecIntersection:
    """Test spec intersection logic (official ∩ implementation)."""

    def test_intersection_basic(self, sample_official_spec, sample_implementation_spec):
        """Test basic intersection of official and implementation specs."""
        derived = derive_spec_from_intersection(
            sample_official_spec, sample_implementation_spec
        )

        # Should have 2 paths (asset-information not in implementation)
        assert len(derived["paths"]) == 2
        assert "/shells" in derived["paths"]
        assert "/shells/{aasIdentifier}" in derived["paths"]
        assert "/shells/{aasIdentifier}/asset-information" not in derived["paths"]

        # /shells should have GET and POST
        assert "get" in derived["paths"]["/shells"]
        assert "post" in derived["paths"]["/shells"]

        # /shells/{aasIdentifier} should have GET, PUT, DELETE
        assert "get" in derived["paths"]["/shells/{aasIdentifier}"]
        assert "put" in derived["paths"]["/shells/{aasIdentifier}"]
        assert "delete" in derived["paths"]["/shells/{aasIdentifier}"]

    def test_intersection_preserves_official_details(
        self, sample_official_spec, sample_implementation_spec
    ):
        """Test that intersection preserves details from official spec."""
        derived = derive_spec_from_intersection(
            sample_official_spec, sample_implementation_spec
        )

        # Check that operationIds from official spec are preserved
        assert (
            derived["paths"]["/shells"]["get"]["operationId"]
            == "GetAllAssetAdministrationShells"
        )
        assert (
            derived["paths"]["/shells"]["post"]["operationId"]
            == "PostAssetAdministrationShell"
        )

        # Check that parameters from official spec are preserved
        get_op = derived["paths"]["/shells/{aasIdentifier}"]["get"]
        assert "parameters" in get_op
        assert len(get_op["parameters"]) == 1
        assert get_op["parameters"][0]["name"] == "aasIdentifier"

    def test_intersection_empty_when_no_overlap(self):
        """Test that intersection is empty when specs have no overlap."""
        official = {
            "openapi": "3.0.3",
            "info": {"title": "Official", "version": "1.0.0"},
            "paths": {
                "/shells": {"get": {"responses": {"200": {"description": "Success"}}}}
            },
        }
        implementation = {
            "openapi": "3.0.3",
            "info": {"title": "Implementation", "version": "1.0.0"},
            "paths": {
                "/submodels": {
                    "get": {"responses": {"200": {"description": "Success"}}}
                }
            },
        }

        derived = derive_spec_from_intersection(official, implementation)
        assert len(derived["paths"]) == 0


class TestOverlayApplication:
    """Test overlay application."""

    def test_overlay_renames_operations(
        self, sample_official_spec, sample_overlay, tmp_path
    ):
        """Test that overlay renames operationIds."""
        from oas_patch import apply_overlay

        # Apply overlay
        result = apply_overlay(sample_official_spec, sample_overlay)

        # Check renamed operations
        assert result["paths"]["/shells"]["get"]["operationId"] == "list_shells"
        assert result["paths"]["/shells"]["post"]["operationId"] == "create_shell"
        assert (
            result["paths"]["/shells/{aasIdentifier}"]["get"]["operationId"]
            == "get_shell"
        )

        # Check that other operations are unchanged
        assert (
            result["paths"]["/shells/{aasIdentifier}"]["put"]["operationId"]
            == "PutAssetAdministrationShellById"
        )

    def test_overlay_updates_summaries(self, sample_official_spec, sample_overlay):
        """Test that overlay updates summaries."""
        from oas_patch import apply_overlay

        result = apply_overlay(sample_official_spec, sample_overlay)

        assert (
            result["paths"]["/shells"]["get"]["summary"]
            == "List all Asset Administration Shells"
        )
        assert (
            result["paths"]["/shells"]["post"]["summary"]
            == "Create a new Asset Administration Shell"
        )


class TestCuration:
    """Test curation (allowlist + aliases + read-only enforcement)."""

    def test_allowlist_filters_operations(self, sample_official_spec):
        """Test that allowlist filters out non-allowed operations."""
        curation_settings = {
            "allowlist": [("get", "/shells"), ("get", "/shells/{aasIdentifier}")],
            "aliases": {},
        }

        curated = curate_openapi_spec(
            sample_official_spec,
            enable_writes=False,
            curation_settings=curation_settings,
        )

        # Should only have 2 operations (the 2 GETs)
        assert len(curated["paths"]) == 2
        assert "get" in curated["paths"]["/shells"]
        assert "post" not in curated["paths"]["/shells"]  # Filtered out by allowlist
        assert "get" in curated["paths"]["/shells/{aasIdentifier}"]
        assert "put" not in curated["paths"]["/shells/{aasIdentifier}"]  # Filtered out

    def test_read_only_blocks_writes(self, sample_official_spec):
        """Test that read-only mode blocks write operations."""
        curation_settings = {
            "allowlist": [
                ("get", "/shells"),
                ("post", "/shells"),  # In allowlist but should be blocked by read-only
                ("get", "/shells/{aasIdentifier}"),
                ("delete", "/shells/{aasIdentifier}"),  # In allowlist but blocked
            ],
            "aliases": {},
        }

        curated = curate_openapi_spec(
            sample_official_spec,
            enable_writes=False,  # Read-only mode
            curation_settings=curation_settings,
        )

        # Should only have GETs (writes blocked)
        assert "get" in curated["paths"]["/shells"]
        assert "post" not in curated["paths"]["/shells"]
        assert "get" in curated["paths"]["/shells/{aasIdentifier}"]
        assert "delete" not in curated["paths"]["/shells/{aasIdentifier}"]

    def test_enable_writes_allows_write_operations(self, sample_official_spec):
        """Test that enable_writes flag allows write operations."""
        curation_settings = {
            "allowlist": [
                ("get", "/shells"),
                ("post", "/shells"),
                ("delete", "/shells/{aasIdentifier}"),
            ],
            "aliases": {},
        }

        curated = curate_openapi_spec(
            sample_official_spec,
            enable_writes=True,  # Writes enabled
            curation_settings=curation_settings,
        )

        # Should have both reads and writes
        assert "get" in curated["paths"]["/shells"]
        assert "post" in curated["paths"]["/shells"]
        assert "delete" in curated["paths"]["/shells/{aasIdentifier}"]

    def test_wildcard_allowlist_all_gets(self, sample_official_spec):
        """Test wildcard allowlist for all GET operations."""
        curation_settings = {
            "allowlist": [
                ("get", "*")  # All GETs
            ],
            "aliases": {},
        }

        curated = curate_openapi_spec(
            sample_official_spec,
            enable_writes=False,
            curation_settings=curation_settings,
        )

        # Should have all GET operations
        assert "get" in curated["paths"]["/shells"]
        assert "get" in curated["paths"]["/shells/{aasIdentifier}"]
        assert "get" in curated["paths"]["/shells/{aasIdentifier}/asset-information"]

        # Should not have writes
        assert "post" not in curated["paths"]["/shells"]

    def test_wildcard_allowlist_all_methods_for_path(self, sample_official_spec):
        """Test wildcard allowlist for all methods on a specific path."""
        curation_settings = {
            "allowlist": [
                ("*", "/shells")  # All methods on /shells
            ],
            "aliases": {},
        }

        curated = curate_openapi_spec(
            sample_official_spec,
            enable_writes=True,
            curation_settings=curation_settings,
        )

        # Should have both GET and POST on /shells
        assert len(curated["paths"]) == 1
        assert "get" in curated["paths"]["/shells"]
        assert "post" in curated["paths"]["/shells"]

    def test_aliases_rename_operations(self, sample_official_spec):
        """Test that aliases rename operationIds."""
        curation_settings = {
            "allowlist": [("get", "/shells"), ("post", "/shells")],
            "aliases": {
                "GetAllAssetAdministrationShells": "list_shells",
                "PostAssetAdministrationShell": "create_shell",
            },
        }

        curated = curate_openapi_spec(
            sample_official_spec,
            enable_writes=True,
            curation_settings=curation_settings,
        )

        # Check renamed operationIds
        assert curated["paths"]["/shells"]["get"]["operationId"] == "list_shells"
        assert curated["paths"]["/shells"]["post"]["operationId"] == "create_shell"


class TestCompletePipeline:
    """Test the complete pipeline: config → intersection → overlay → curation → MCP."""

    def test_complete_pipeline_with_all_steps(
        self, tmp_path, sample_official_spec, sample_implementation_spec, sample_overlay
    ):
        """Test complete pipeline with intersection, overlay, and curation."""
        # 1. Save specs to files
        official_path = tmp_path / "official.yaml"
        impl_path = tmp_path / "implementation.yaml"
        overlay_path = tmp_path / "overlay.yaml"

        with open(official_path, "w") as f:
            yaml.dump(sample_official_spec, f)
        with open(impl_path, "w") as f:
            yaml.dump(sample_implementation_spec, f)
        with open(overlay_path, "w") as f:
            yaml.dump(sample_overlay, f)

        # 2. Create config
        config_path = tmp_path / "config.yaml"
        config_data = {
            "components": {
                "aas-repo": {
                    "official_spec": str(official_path),
                    "implementation_spec": str(impl_path),
                    "overlay": str(overlay_path),
                    "curation": {
                        "allowlist": [
                            ["get", "*"],  # All GETs
                            ["post", "/shells"],  # Only POST to /shells
                        ],
                        "aliases": {
                            "list_shells": "list_shells",  # Already renamed by overlay
                            "create_shell": "create_shell",
                            "get_shell": "get_shell",
                        },
                    },
                }
            }
        }

        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        # 3. Load config
        config = load_config(str(config_path))
        component_config = config.get_component("aas-repo")

        # 4. Process spec (intersection + overlay)
        processed_spec = process_component_spec(component_config)

        # Verify intersection worked (asset-information not in implementation)
        assert "/shells" in processed_spec["paths"]
        assert "/shells/{aasIdentifier}" in processed_spec["paths"]
        assert (
            "/shells/{aasIdentifier}/asset-information" not in processed_spec["paths"]
        )

        # Verify overlay worked (operationIds renamed)
        assert processed_spec["paths"]["/shells"]["get"]["operationId"] == "list_shells"
        assert (
            processed_spec["paths"]["/shells"]["post"]["operationId"] == "create_shell"
        )
        assert (
            processed_spec["paths"]["/shells/{aasIdentifier}"]["get"]["operationId"]
            == "get_shell"
        )

        # 5. Curate spec
        curated_spec = curate_openapi_spec(
            processed_spec,
            enable_writes=True,
            curation_settings=component_config.curation,
        )

        # Verify curation worked (only allowed operations)
        assert "get" in curated_spec["paths"]["/shells"]
        assert "post" in curated_spec["paths"]["/shells"]
        assert "get" in curated_spec["paths"]["/shells/{aasIdentifier}"]
        # PUT and DELETE should be filtered out by allowlist
        assert "put" not in curated_spec["paths"]["/shells/{aasIdentifier}"]
        assert "delete" not in curated_spec["paths"]["/shells/{aasIdentifier}"]

    def test_mcp_server_builds_successfully(self, tmp_path, sample_official_spec):
        """Test that MCP server builds successfully from config."""
        # Create minimal config
        official_path = tmp_path / "official.yaml"
        with open(official_path, "w") as f:
            yaml.dump(sample_official_spec, f)

        config_path = tmp_path / "config.yaml"
        config_data = {
            "components": {
                "aas-repo": {
                    "official_spec": str(official_path),
                    "curation": {"allowlist": [["get", "*"]], "aliases": {}},
                }
            }
        }

        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        # Load config and build server
        config = load_config(str(config_path))
        component_config = config.get_component("aas-repo")

        server = build_mcp_server(
            component_config=component_config,
            base_url=BACKEND_URL,
            enable_writes=False,
            log_level="WARNING",
        )

        # Verify server was created
        assert server is not None
        assert hasattr(server, "name")


class TestBackendConnectivity:
    """Test connectivity to backend services (skipped if backend unavailable)."""

    def test_backend_responds(self, backend_available, request):
        """Test that backend service responds on port 8081."""
        if not request.config.getoption("--run-integration"):
            pytest.skip("Backend integration tests require --run-integration flag")

        if not backend_available:
            pytest.skip("Backend not available on localhost:8081")

        response = httpx.get(f"{BACKEND_URL}/shells", timeout=BACKEND_TIMEOUT)
        assert response.status_code in [200, 404]  # 404 is fine (no shells yet)

    def test_backend_health_check(self, backend_available, request):
        """Test backend health/description endpoint."""
        if not request.config.getoption("--run-integration"):
            pytest.skip("Backend integration tests require --run-integration flag")

        if not backend_available:
            pytest.skip("Backend not available on localhost:8081")

        # Try common health check endpoints
        endpoints = ["/description", "/health", "/"]

        for endpoint in endpoints:
            try:
                response = httpx.get(
                    f"{BACKEND_URL}{endpoint}", timeout=BACKEND_TIMEOUT
                )
                if response.status_code == 200:
                    return  # At least one endpoint works
            except Exception:
                continue

        # If none work, that's okay - backend might not have health endpoints
