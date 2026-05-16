# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for server module.

Tests the MCP server builder orchestration.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from aas_mcp_server.server import (
    build_mcp_server,
)
from aas_mcp_server.constants import DEFAULT_LOG_LEVEL, SERVER_NAME_FORMAT
from aas_mcp_server.config import ComponentConfig


class TestBuildMcpServer:
    """Tests for build_mcp_server function."""

    def _create_mock_component_config(self, component_name="aas-repo"):
        """Create a mock ComponentConfig for testing."""
        mock_config = MagicMock(spec=ComponentConfig)
        mock_config.component_name = component_name
        mock_config.curation = None
        mock_config.official_spec = Path("/app/specs/official.yaml")
        mock_config.implementation_spec = None
        mock_config.overlay = None
        mock_config.has_both_specs.return_value = False
        return mock_config

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_calls_configure_logging_with_provided_level(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that configure_logging is called with provided log level."""
        mock_process_spec.return_value = {"paths": {}}
        mock_component_config = self._create_mock_component_config()

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
            log_level="DEBUG",
        )

        mock_configure_logging.assert_called_once_with("DEBUG", transport="stdio")

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_calls_configure_logging_with_default_level(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that configure_logging uses default log level when not provided."""
        mock_process_spec.return_value = {"paths": {}}
        mock_component_config = self._create_mock_component_config()

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        mock_configure_logging.assert_called_once_with(DEFAULT_LOG_LEVEL, transport="stdio")

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_processes_component_spec(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that process_component_spec is called with component config."""
        mock_spec = {"paths": {}}
        mock_process_spec.return_value = mock_spec
        mock_component_config = self._create_mock_component_config()

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        mock_process_spec.assert_called_once_with(mock_component_config)

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_curates_spec_with_enable_writes_false(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that curate_openapi_spec is called with enable_writes=False."""
        mock_spec = {"paths": {}}
        flat_spec = {"paths": {}}
        mock_process_spec.return_value = mock_spec
        mock_flatten.return_value = flat_spec
        mock_component_config = self._create_mock_component_config()

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        mock_curate.assert_called_once_with(flat_spec, enable_writes=False, curation_settings=None)

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_curates_spec_with_enable_writes_true(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that curate_openapi_spec is called with enable_writes=True."""
        mock_spec = {"paths": {}}
        flat_spec = {"paths": {}}
        mock_process_spec.return_value = mock_spec
        mock_flatten.return_value = flat_spec
        mock_component_config = self._create_mock_component_config()

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=True,
        )

        mock_curate.assert_called_once_with(flat_spec, enable_writes=True, curation_settings=None)

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_curates_spec_with_curation_settings(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that curate_openapi_spec is called with curation settings from config."""
        mock_spec = {"paths": {}}
        flat_spec = {"paths": {}}
        mock_process_spec.return_value = mock_spec
        mock_flatten.return_value = flat_spec
        mock_component_config = self._create_mock_component_config()
        mock_curation_settings = {"allowlist": [("get", "/shells")]}
        mock_component_config.curation = mock_curation_settings

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        mock_curate.assert_called_once_with(flat_spec, enable_writes=False, curation_settings=mock_curation_settings)

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_builds_http_client_with_base_url(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that build_async_client is called with correct base_url."""
        mock_process_spec.return_value = {"paths": {}}
        mock_component_config = self._create_mock_component_config()

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://prod-server:9000",
            enable_writes=False,
        )

        mock_build_client.assert_called_once_with(base_url="http://prod-server:9000")

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_creates_fastmcp_server_with_curated_spec(
        self,
        mock_fastmcp_class,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that FastMCP.from_openapi is called with pruned curated spec."""
        mock_spec = {"paths": {}}
        mock_curated_spec = {"paths": {"/shells": {}}}
        mock_pruned_spec = {"paths": {"/shells": {}}, "components": {"schemas": {}}}
        mock_process_spec.return_value = mock_spec
        mock_curate.return_value = mock_curated_spec
        mock_prune.return_value = mock_pruned_spec
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client
        mock_component_config = self._create_mock_component_config("aas-repo")

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        mock_fastmcp_class.from_openapi.assert_called_once_with(
            openapi_spec=mock_pruned_spec,
            client=mock_client,
            name=SERVER_NAME_FORMAT.format(component_name="aas-repo"),
        )

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_returns_fastmcp_instance(
        self,
        mock_fastmcp_class,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Test that build_mcp_server returns a FastMCP instance."""
        mock_process_spec.return_value = {"paths": {}}
        mock_mcp_instance = MagicMock()
        mock_fastmcp_class.from_openapi.return_value = mock_mcp_instance
        mock_component_config = self._create_mock_component_config()

        result = build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        assert result == mock_mcp_instance

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_flattens_spec_before_curation(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """flatten_spec_schemas is called on the raw spec, and curation receives the flattened result."""
        raw_spec = {"paths": {}, "components": {"schemas": {"Shell": {"allOf": []}}}}
        flat_spec = {"paths": {}, "components": {"schemas": {"Shell": {"type": "object"}}}}
        mock_process_spec.return_value = raw_spec
        mock_flatten.return_value = flat_spec
        mock_prune.return_value = flat_spec
        mock_component_config = self._create_mock_component_config()

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        mock_flatten.assert_called_once_with(raw_spec)
        # curate receives the flattened spec
        args, kwargs = mock_curate.call_args
        assert args[0] is flat_spec or kwargs.get("spec") is flat_spec

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_prunes_schemas_after_curation(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """prune_unused_schemas is called on the curated spec, and FastMCP receives the pruned result."""
        raw_spec = {"paths": {}}
        curated_spec = {"paths": {"/shells": {}}, "components": {"schemas": {"Shell": {}, "Orphan": {}}}}
        pruned_spec = {"paths": {"/shells": {}}, "components": {"schemas": {"Shell": {}}}}
        mock_process_spec.return_value = raw_spec
        mock_flatten.return_value = raw_spec
        mock_curate.return_value = curated_spec
        mock_prune.return_value = pruned_spec
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client
        mock_component_config = self._create_mock_component_config("aas-repo")

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        mock_prune.assert_called_once_with(curated_spec)
        mock_fastmcp.from_openapi.assert_called_once_with(
            openapi_spec=pruned_spec,
            client=mock_client,
            name=SERVER_NAME_FORMAT.format(component_name="aas-repo"),
        )

    @patch("aas_mcp_server.server.configure_logging")
    @patch("aas_mcp_server.server.process_component_spec")
    @patch("aas_mcp_server.server.flatten_spec_schemas")
    @patch("aas_mcp_server.server.curate_openapi_spec")
    @patch("aas_mcp_server.server.prune_unused_schemas")
    @patch("aas_mcp_server.server.build_async_client")
    @patch("aas_mcp_server.server.FastMCP")
    def test_pipeline_execution_order(
        self,
        mock_fastmcp,
        mock_build_client,
        mock_prune,
        mock_curate,
        mock_flatten,
        mock_process_spec,
        mock_configure_logging,
    ):
        """Pipeline steps execute in correct order: load → flatten → curate → prune → client → FastMCP."""
        call_order = []
        mock_component_config = self._create_mock_component_config()

        mock_configure_logging.side_effect = lambda *a, **kw: call_order.append("configure_logging")
        mock_process_spec.side_effect = lambda *a: (call_order.append("process_spec"), {"paths": {}})[1]
        mock_flatten.side_effect = lambda *a: (call_order.append("flatten"), {"paths": {}})[1]
        mock_curate.side_effect = lambda *a, **kw: (call_order.append("curate"), {"paths": {}})[1]
        mock_prune.side_effect = lambda *a: (call_order.append("prune"), {"paths": {}})[1]
        mock_build_client.side_effect = lambda **kw: (call_order.append("build_client"), MagicMock())[1]
        mock_fastmcp.from_openapi.side_effect = lambda **kw: (call_order.append("fastmcp"), MagicMock())[1]

        build_mcp_server(
            component_config=mock_component_config,
            base_url="http://localhost:8080",
            enable_writes=False,
        )

        assert call_order == [
            "configure_logging",
            "process_spec",
            "flatten",
            "curate",
            "prune",
            "build_client",
            "fastmcp",
        ]


class TestConstants:
    """Tests for module constants."""

    def test_default_log_level_is_info(self):
        """Test that default log level is INFO."""
        assert DEFAULT_LOG_LEVEL == "INFO"

    def test_server_name_format_has_placeholder(self):
        """Test that server name format has component_name placeholder."""
        assert "{component_name}" in SERVER_NAME_FORMAT

    def test_server_name_format_produces_correct_name(self):
        """Test that server name format produces expected string."""
        result = SERVER_NAME_FORMAT.format(component_name="test-component")
        assert "AAS MCP Server" in result
        assert "test-component" in result
