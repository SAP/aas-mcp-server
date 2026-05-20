# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for cli module.

Tests command-line interface argument parsing and configuration.
"""

import os
from unittest.mock import MagicMock, patch
import pytest

from aas_mcp_server.cli import (
    main,
    ENV_VAR_MCP_TRANSPORT,
    ENV_VAR_AAS_MCP_ENABLE_WRITES,
    ENV_VAR_LOG_LEVEL,
    ENV_VAR_AAS_BASE_URL,
    DEFAULT_TRANSPORT,
    DEFAULT_LOG_LEVEL,
    ENABLE_WRITES_TRUE_VALUE,
    CLI_PROGRAM_NAME,
)


class TestMain:
    """Tests for main CLI function."""

    @patch("aas_mcp_server.cli.build_mcp_server")
    @patch("aas_mcp_server.cli.load_config")
    @patch(
        "sys.argv",
        [
            "aas-mcp-server",
            "--component",
            "aas-repo",
            "--base-url",
            "http://localhost:8080",
        ],
    )
    def test_main_builds_server_with_config(self, mock_load_config, mock_build_server):
        """Test that main builds server using configuration from config file."""
        # Setup mocks
        mock_component_config = MagicMock()
        mock_component_config.component_name = "aas-repo"
        mock_config = MagicMock()
        mock_config.get_component.return_value = mock_component_config
        mock_config.config_path = "/app/config/config.yaml"
        mock_config.components = {"aas-repo": mock_component_config}
        mock_load_config.return_value = mock_config

        mock_mcp = MagicMock()
        mock_build_server.return_value = mock_mcp

        main()

        mock_build_server.assert_called_once()
        call_kwargs = mock_build_server.call_args.kwargs
        assert call_kwargs["component_config"] == mock_component_config
        assert call_kwargs["base_url"] == "http://localhost:8080"
        assert call_kwargs["enable_writes"] is False
        mock_mcp.run.assert_called_once()

    @patch("aas_mcp_server.cli.build_mcp_server")
    @patch("aas_mcp_server.cli.load_config")
    @patch(
        "sys.argv",
        [
            "aas-mcp-server",
            "--component",
            "aas-repo",
            "--base-url",
            "http://custom:9000",
        ],
    )
    def test_main_uses_custom_base_url_from_arg(
        self, mock_load_config, mock_build_server
    ):
        """Test that main uses custom base URL from command line."""
        mock_component_config = MagicMock()
        mock_config = MagicMock()
        mock_config.get_component.return_value = mock_component_config
        mock_config.config_path = "/app/config/config.yaml"
        mock_config.components = {"aas-repo": mock_component_config}
        mock_load_config.return_value = mock_config

        mock_mcp = MagicMock()
        mock_build_server.return_value = mock_mcp

        main()

        call_kwargs = mock_build_server.call_args.kwargs
        assert call_kwargs["base_url"] == "http://custom:9000"

    @patch("aas_mcp_server.cli.build_mcp_server")
    @patch("aas_mcp_server.cli.load_config")
    @patch.dict(os.environ, {ENV_VAR_AAS_BASE_URL: "http://env-server:8888"})
    @patch("sys.argv", ["aas-mcp-server", "--component", "aas-repo"])
    def test_main_uses_base_url_from_env(self, mock_load_config, mock_build_server):
        """Test that main uses base URL from environment variable."""
        mock_component_config = MagicMock()
        mock_config = MagicMock()
        mock_config.get_component.return_value = mock_component_config
        mock_config.config_path = "/app/config/config.yaml"
        mock_config.components = {"aas-repo": mock_component_config}
        mock_load_config.return_value = mock_config

        mock_mcp = MagicMock()
        mock_build_server.return_value = mock_mcp

        main()

        call_kwargs = mock_build_server.call_args.kwargs
        assert call_kwargs["base_url"] == "http://env-server:8888"

    @patch("aas_mcp_server.cli.build_mcp_server")
    @patch("aas_mcp_server.cli.load_config")
    @patch.dict(os.environ, {ENV_VAR_AAS_BASE_URL: "http://env-server:8888"})
    @patch(
        "sys.argv",
        [
            "aas-mcp-server",
            "--component",
            "aas-repo",
            "--base-url",
            "http://arg-server:7777",
        ],
    )
    def test_main_prioritizes_arg_over_env_for_base_url(
        self, mock_load_config, mock_build_server
    ):
        """Test that command line arg takes precedence over env var."""
        mock_component_config = MagicMock()
        mock_config = MagicMock()
        mock_config.get_component.return_value = mock_component_config
        mock_config.config_path = "/app/config/config.yaml"
        mock_config.components = {"aas-repo": mock_component_config}
        mock_load_config.return_value = mock_config

        mock_mcp = MagicMock()
        mock_build_server.return_value = mock_mcp

        main()

        call_kwargs = mock_build_server.call_args.kwargs
        assert call_kwargs["base_url"] == "http://arg-server:7777"

    @patch("aas_mcp_server.cli.build_mcp_server")
    @patch("aas_mcp_server.cli.load_config")
    @patch(
        "sys.argv",
        [
            "aas-mcp-server",
            "--component",
            "aas-repo",
            "--base-url",
            "http://localhost:8080",
            "--enable-writes",
        ],
    )
    def test_main_enables_writes_from_arg(self, mock_load_config, mock_build_server):
        """Test that main enables writes when flag is provided."""
        mock_component_config = MagicMock()
        mock_config = MagicMock()
        mock_config.get_component.return_value = mock_component_config
        mock_config.config_path = "/app/config/config.yaml"
        mock_config.components = {"aas-repo": mock_component_config}
        mock_load_config.return_value = mock_config

        mock_mcp = MagicMock()
        mock_build_server.return_value = mock_mcp

        main()

        call_kwargs = mock_build_server.call_args.kwargs
        assert call_kwargs["enable_writes"] is True

    @patch("aas_mcp_server.cli.build_mcp_server")
    @patch("aas_mcp_server.cli.load_config")
    @patch.dict(
        os.environ,
        {
            ENV_VAR_AAS_MCP_ENABLE_WRITES: ENABLE_WRITES_TRUE_VALUE,
            ENV_VAR_AAS_BASE_URL: "http://localhost:8080",
        },
    )
    @patch("sys.argv", ["aas-mcp-server", "--component", "aas-repo"])
    def test_main_enables_writes_from_env(self, mock_load_config, mock_build_server):
        """Test that main enables writes from environment variable."""
        mock_component_config = MagicMock()
        mock_config = MagicMock()
        mock_config.get_component.return_value = mock_component_config
        mock_config.config_path = "/app/config/config.yaml"
        mock_config.components = {"aas-repo": mock_component_config}
        mock_load_config.return_value = mock_config

        mock_mcp = MagicMock()
        mock_build_server.return_value = mock_mcp

        main()

        call_kwargs = mock_build_server.call_args.kwargs
        assert call_kwargs["enable_writes"] is True

    @patch("aas_mcp_server.cli.build_mcp_server")
    @patch("aas_mcp_server.cli.load_config")
    @patch.dict(
        os.environ,
        {
            ENV_VAR_AAS_MCP_ENABLE_WRITES: "0",
            ENV_VAR_AAS_BASE_URL: "http://localhost:8080",
        },
    )
    @patch("sys.argv", ["aas-mcp-server", "--component", "aas-repo"])
    def test_main_disables_writes_when_env_not_1(
        self, mock_load_config, mock_build_server
    ):
        """Test that writes are disabled when env var is not '1'."""
        mock_component_config = MagicMock()
        mock_config = MagicMock()
        mock_config.get_component.return_value = mock_component_config
        mock_config.config_path = "/app/config/config.yaml"
        mock_config.components = {"aas-repo": mock_component_config}
        mock_load_config.return_value = mock_config

        mock_mcp = MagicMock()
        mock_build_server.return_value = mock_mcp

        main()

        call_kwargs = mock_build_server.call_args.kwargs
        assert call_kwargs["enable_writes"] is False

    @patch("aas_mcp_server.cli.build_mcp_server")
    @patch("aas_mcp_server.cli.load_config")
    @patch(
        "sys.argv",
        [
            "aas-mcp-server",
            "--component",
            "aas-repo",
            "--base-url",
            "http://localhost:8080",
            "--log-level",
            "DEBUG",
        ],
    )
    def test_main_uses_custom_log_level_from_arg(
        self, mock_load_config, mock_build_server
    ):
        """Test that main uses custom log level from command line."""
        mock_component_config = MagicMock()
        mock_config = MagicMock()
        mock_config.get_component.return_value = mock_component_config
        mock_config.config_path = "/app/config/config.yaml"
        mock_config.components = {"aas-repo": mock_component_config}
        mock_load_config.return_value = mock_config

        mock_mcp = MagicMock()
        mock_build_server.return_value = mock_mcp

        main()

        call_kwargs = mock_build_server.call_args.kwargs
        assert call_kwargs["log_level"] == "DEBUG"

    @patch("aas_mcp_server.cli.build_mcp_server")
    @patch("aas_mcp_server.cli.load_config")
    @patch.dict(
        os.environ,
        {ENV_VAR_LOG_LEVEL: "WARNING", ENV_VAR_AAS_BASE_URL: "http://localhost:8080"},
    )
    @patch("sys.argv", ["aas-mcp-server", "--component", "aas-repo"])
    def test_main_uses_log_level_from_env(self, mock_load_config, mock_build_server):
        """Test that main uses log level from environment variable."""
        mock_component_config = MagicMock()
        mock_config = MagicMock()
        mock_config.get_component.return_value = mock_component_config
        mock_config.config_path = "/app/config/config.yaml"
        mock_config.components = {"aas-repo": mock_component_config}
        mock_load_config.return_value = mock_config

        mock_mcp = MagicMock()
        mock_build_server.return_value = mock_mcp

        main()

        call_kwargs = mock_build_server.call_args.kwargs
        assert call_kwargs["log_level"] == "WARNING"

    @patch("aas_mcp_server.cli.load_config")
    @patch("sys.argv", ["aas-mcp-server", "--component", "aas-repo"])
    def test_main_exits_when_base_url_missing(self, mock_load_config):
        """Test that main exits with error when base URL is not provided."""
        mock_component_config = MagicMock()
        mock_config = MagicMock()
        mock_config.get_component.return_value = mock_component_config
        mock_config.config_path = "/app/config/config.yaml"
        mock_config.components = {"aas-repo": mock_component_config}
        mock_load_config.return_value = mock_config

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1


class TestConstants:
    """Tests for module constants."""

    def test_env_var_names_are_correct(self):
        """Test that environment variable names are correct."""
        assert ENV_VAR_MCP_TRANSPORT == "MCP_TRANSPORT"
        assert ENV_VAR_AAS_MCP_ENABLE_WRITES == "AAS_MCP_ENABLE_WRITES"
        assert ENV_VAR_LOG_LEVEL == "LOG_LEVEL"
        assert ENV_VAR_AAS_BASE_URL == "AAS_BASE_URL"

    def test_default_values_are_correct(self):
        """Test that default values are correct."""
        assert DEFAULT_TRANSPORT == "stdio"
        assert DEFAULT_LOG_LEVEL == "INFO"
        assert ENABLE_WRITES_TRUE_VALUE == "1"

    def test_cli_program_name_is_correct(self):
        """Test that CLI program name is correct."""
        assert CLI_PROGRAM_NAME == "aas-mcp-server"
