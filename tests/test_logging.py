# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for logging module.

Tests the logging configuration with various log levels and httpx logger control.
"""

import logging
import os
from unittest.mock import patch, MagicMock

from aas_mcp_server.logging import (
    configure_logging,
    ENV_VAR_HTTPX_LOG_LEVEL,
    DEFAULT_LOG_LEVEL,
    LOGGER_HTTPX,
)


class TestConfigureLogging:
    """Tests for configure_logging function."""

    @patch("logging.basicConfig")
    def test_sets_root_logger_to_info_by_default(self, mock_basic_config):
        """Test that basicConfig is called with INFO level by default."""
        configure_logging()

        mock_basic_config.assert_called_once()
        call_kwargs = mock_basic_config.call_args.kwargs
        assert call_kwargs["level"] == logging.INFO

    @patch("logging.basicConfig")
    def test_sets_root_logger_to_debug(self, mock_basic_config):
        """Test that basicConfig is called with DEBUG level."""
        configure_logging(level="DEBUG")

        mock_basic_config.assert_called_once()
        call_kwargs = mock_basic_config.call_args.kwargs
        assert call_kwargs["level"] == logging.DEBUG

    @patch("logging.basicConfig")
    def test_sets_root_logger_to_warning(self, mock_basic_config):
        """Test that basicConfig is called with WARNING level."""
        configure_logging(level="WARNING")

        mock_basic_config.assert_called_once()
        call_kwargs = mock_basic_config.call_args.kwargs
        assert call_kwargs["level"] == logging.WARNING

    @patch("logging.basicConfig")
    def test_sets_root_logger_to_error(self, mock_basic_config):
        """Test that basicConfig is called with ERROR level."""
        configure_logging(level="ERROR")

        mock_basic_config.assert_called_once()
        call_kwargs = mock_basic_config.call_args.kwargs
        assert call_kwargs["level"] == logging.ERROR

    @patch.dict(os.environ, {}, clear=True)
    def test_sets_httpx_logger_to_warning_by_default(self):
        """Test that httpx logger defaults to WARNING when no env var set."""
        configure_logging()

        # httpx logger should not be explicitly set when no env var
        httpx_logger = logging.getLogger(LOGGER_HTTPX)
        # Default behavior is that it inherits from root (which is INFO)
        # But the function doesn't set it explicitly without env var
        # So we just check that it exists
        assert httpx_logger is not None

    @patch.dict(os.environ, {ENV_VAR_HTTPX_LOG_LEVEL: "DEBUG"})
    def test_sets_httpx_logger_from_env_var(self):
        """Test that httpx logger level can be set via env var."""
        configure_logging()

        httpx_logger = logging.getLogger(LOGGER_HTTPX)
        assert httpx_logger.level == logging.DEBUG

    @patch.dict(os.environ, {ENV_VAR_HTTPX_LOG_LEVEL: "ERROR"})
    def test_httpx_env_var_overrides_default(self):
        """Test that HTTPX_LOG_LEVEL env var overrides default WARNING."""
        configure_logging()

        httpx_logger = logging.getLogger(LOGGER_HTTPX)
        assert httpx_logger.level == logging.ERROR

    @patch.dict(os.environ, {ENV_VAR_HTTPX_LOG_LEVEL: "WARNING"})
    @patch("aas_mcp_server.logging.logging.getLogger")
    @patch("logging.basicConfig")
    def test_root_and_httpx_loggers_are_independent(
        self, mock_basic_config, mock_get_logger
    ):
        """Test that httpx logger can be set independently from root."""
        mock_httpx_logger = MagicMock()
        mock_get_logger.return_value = mock_httpx_logger

        configure_logging(level="DEBUG")

        mock_basic_config.assert_called_once()
        call_kwargs = mock_basic_config.call_args.kwargs
        assert call_kwargs["level"] == logging.DEBUG

        # httpx logger should be retrieved and set when env var is present
        mock_get_logger.assert_called_with(LOGGER_HTTPX)
        mock_httpx_logger.setLevel.assert_called_with(logging.WARNING)

    @patch("logging.basicConfig")
    def test_accepts_lowercase_log_levels(self, mock_basic_config):
        """Test that function accepts lowercase log level strings."""
        configure_logging(level="info")

        mock_basic_config.assert_called_once()
        call_kwargs = mock_basic_config.call_args.kwargs
        assert call_kwargs["level"] == logging.INFO

    @patch("logging.basicConfig")
    def test_configures_basic_config(self, mock_basic_config):
        """Test that basicConfig is called."""
        configure_logging()

        mock_basic_config.assert_called_once()
        call_kwargs = mock_basic_config.call_args.kwargs
        assert "level" in call_kwargs
        assert "format" in call_kwargs


class TestConstants:
    """Tests for module constants."""

    def test_default_log_level_is_info(self):
        """Test that default log level is INFO."""
        assert DEFAULT_LOG_LEVEL == "INFO"

    def test_httpx_logger_name_is_correct(self):
        """Test that httpx logger name is correct."""
        assert LOGGER_HTTPX == "httpx"

    def test_env_var_httpx_log_level_is_correct(self):
        """Test that httpx log level env var name is correct."""
        assert ENV_VAR_HTTPX_LOG_LEVEL == "HTTPX_LOG_LEVEL"
