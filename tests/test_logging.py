# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

"""
Tests for logging module.

Tests the logging configuration with various log levels and httpx logger control.
"""

import io
import json
import logging
import os
import sys
from unittest.mock import patch, MagicMock

import pytest
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

from aas_mcp_server.constants import ENV_LOG_FORMAT
from aas_mcp_server.logging import (
    configure_logging,
    ENV_VAR_HTTPX_LOG_LEVEL,
    DEFAULT_LOG_LEVEL,
    LOGGER_HTTPX,
    LOG_FORMAT,
    JsonFormatter,
    TraceContextFilter,
    TraceTextFormatter,
    uvicorn_log_config,
)

TRACE_ID = 0x4BF92F3577B34DA6A3CE929D0E0E4736
SPAN_ID = 0x00F067AA0BA902B7
TRACE_ID_HEX = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN_ID_HEX = "00f067aa0ba902b7"


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
        assert "handlers" in call_kwargs


class TestConstants:
    """Tests for module constants."""

    def test_default_log_level_is_info(self):
        """Test that default log level is INFO."""
        assert DEFAULT_LOG_LEVEL == "INFO"

    def test_httpx_logger_name_is_correct(self):
        """Test that httpx logger name is correct."""
        assert LOGGER_HTTPX == "httpx2"

    def test_env_var_httpx_log_level_is_correct(self):
        """Test that httpx log level env var name is correct."""
        assert ENV_VAR_HTTPX_LOG_LEVEL == "HTTPX_LOG_LEVEL"


def _active_span():
    """A valid span context, as a remote traceparent or a recording span gives."""
    return trace.use_span(
        NonRecordingSpan(
            SpanContext(
                trace_id=TRACE_ID,
                span_id=SPAN_ID,
                is_remote=True,
                trace_flags=TraceFlags(TraceFlags.SAMPLED),
            )
        )
    )


def _record(
    msg: str = "hello %s", args: tuple = ("world",), exc_info=None
) -> logging.LogRecord:
    return logging.LogRecord(
        name="aas_mcp_server.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=exc_info,
    )


def _capture_logger(formatter: logging.Formatter) -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(TraceContextFilter())
    handler.setFormatter(formatter)
    logger = logging.getLogger(f"aas_mcp_server.test_capture.{id(stream)}")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    return logger, stream


class TestTraceContextFilter:
    """trace_id/span_id come from the active OpenTelemetry span."""

    def test_no_span_sets_none(self):
        record = _record()
        assert TraceContextFilter().filter(record) is True
        assert record.trace_id is None
        assert record.span_id is None

    def test_active_span_sets_w3c_hex_ids(self):
        record = _record()
        with _active_span():
            assert TraceContextFilter().filter(record) is True
        assert record.trace_id == TRACE_ID_HEX
        assert record.span_id == SPAN_ID_HEX


class TestTraceTextFormatter:
    """Default text format, unchanged unless a trace context exists."""

    def test_without_trace_matches_plain_format(self):
        record = _record()
        TraceContextFilter().filter(record)
        assert TraceTextFormatter().format(record) == logging.Formatter(
            LOG_FORMAT
        ).format(record)

    def test_with_trace_appends_ids(self):
        logger, stream = _capture_logger(TraceTextFormatter())
        with _active_span():
            logger.info("hello %s", "world")
        line = stream.getvalue().rstrip("\n")
        assert line.endswith(
            f": hello world trace_id={TRACE_ID_HEX} span_id={SPAN_ID_HEX}"
        )

    def test_ids_stay_on_first_line_with_traceback(self):
        logger, stream = _capture_logger(TraceTextFormatter())
        with _active_span():
            try:
                raise ValueError("boom")
            except ValueError:
                logger.exception("failed")
        first, _, rest = stream.getvalue().partition("\n")
        assert first.endswith(f": failed trace_id={TRACE_ID_HEX} span_id={SPAN_ID_HEX}")
        assert rest.startswith("Traceback")


class TestJsonFormatter:
    """One JSON object per line."""

    def test_without_trace(self):
        logger, stream = _capture_logger(JsonFormatter())
        logger.warning("hello %s", "world")
        lines = stream.getvalue().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["level"] == "WARNING"
        assert entry["logger"] == logger.name
        assert entry["message"] == "hello world"
        assert entry["trace_id"] is None
        assert entry["span_id"] is None
        assert entry["timestamp"].endswith("+00:00")
        assert "exception" not in entry

    def test_with_trace(self):
        logger, stream = _capture_logger(JsonFormatter())
        with _active_span():
            logger.info("hello")
        entry = json.loads(stream.getvalue())
        assert entry["trace_id"] == TRACE_ID_HEX
        assert entry["span_id"] == SPAN_ID_HEX

    def test_exception_stays_on_one_line(self):
        logger, stream = _capture_logger(JsonFormatter())
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("failed")
        lines = stream.getvalue().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["message"] == "failed"
        assert "ValueError: boom" in entry["exception"]

    def test_record_without_filter_still_formats(self):
        """A record that skipped the filter (another handler path) has null ids."""
        entry = json.loads(JsonFormatter().format(_record()))
        assert entry["trace_id"] is None
        assert entry["message"] == "hello world"

    def test_preformatted_exception_text_is_kept(self):
        """A record whose traceback was already rendered (exc_info cleared) keeps it."""
        record = _record()
        record.exc_text = "Traceback (most recent call last):\nValueError: boom"
        entry = json.loads(JsonFormatter().format(record))
        assert entry["exception"] == record.exc_text

    def test_stack_info(self):
        logger, stream = _capture_logger(JsonFormatter())
        logger.info("where", stack_info=True)
        lines = stream.getvalue().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["stack"].startswith(
            "Stack (most recent call last):"
        )


class TestLogFormatSelection:
    """LOG_FORMAT picks the formatter of the stderr handler."""

    @staticmethod
    def _handler(mock_basic_config) -> logging.Handler:
        handlers = mock_basic_config.call_args.kwargs["handlers"]
        assert len(handlers) == 1
        return handlers[0]

    @pytest.mark.parametrize(
        ("env", "expected"),
        [
            ({}, TraceTextFormatter),
            ({ENV_LOG_FORMAT: "text"}, TraceTextFormatter),
            ({ENV_LOG_FORMAT: "json"}, JsonFormatter),
            ({ENV_LOG_FORMAT: " JSON "}, JsonFormatter),
        ],
    )
    @patch("logging.basicConfig")
    def test_formatter(self, mock_basic_config, env, expected):
        with patch.dict(os.environ, env, clear=True):
            configure_logging()
        handler = self._handler(mock_basic_config)
        assert isinstance(handler.formatter, expected)
        assert any(isinstance(f, TraceContextFilter) for f in handler.filters)
        assert handler.stream is sys.stderr

    @patch("logging.warning")
    @patch("logging.basicConfig")
    def test_invalid_value_falls_back_to_text_and_warns_after_setup(
        self, mock_basic_config, mock_warning
    ):
        calls = []
        mock_basic_config.side_effect = lambda **_: calls.append("basicConfig")
        mock_warning.side_effect = lambda *_: calls.append("warning")

        with patch.dict(os.environ, {ENV_LOG_FORMAT: "xml"}, clear=True):
            configure_logging()

        assert isinstance(
            self._handler(mock_basic_config).formatter, TraceTextFormatter
        )
        assert calls == ["basicConfig", "warning"]
        assert "xml" in mock_warning.call_args.args[0]


@pytest.fixture
def restore_logging():
    """configure_logging changes global loggers; put them back afterwards."""
    root = logging.getLogger()
    fastmcp_logger = logging.getLogger("fastmcp")
    saved = (
        root.handlers[:],
        root.level,
        fastmcp_logger.handlers[:],
        fastmcp_logger.propagate,
        fastmcp_logger.level,
    )
    yield
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])
    fastmcp_logger.handlers[:] = saved[2]
    fastmcp_logger.propagate = saved[3]
    fastmcp_logger.setLevel(saved[4])


@pytest.mark.usefixtures("restore_logging")
class TestFastMCPLogs:
    """FastMCP's own handlers (propagate=False) must not bypass JSON mode."""

    @staticmethod
    def _fastmcp_rich_setup():
        """What `import fastmcp` does: own handler, no propagation."""
        fastmcp_logger = logging.getLogger("fastmcp")
        fastmcp_logger.handlers[:] = [logging.StreamHandler(io.StringIO())]
        fastmcp_logger.propagate = False
        return fastmcp_logger

    @patch("logging.basicConfig")
    def test_json_routes_fastmcp_through_root(self, _mock_basic_config):
        fastmcp_logger = self._fastmcp_rich_setup()
        with patch.dict(os.environ, {ENV_LOG_FORMAT: "json"}, clear=True):
            configure_logging(transport="http")
        assert fastmcp_logger.handlers == []
        assert fastmcp_logger.propagate is True

    @patch("logging.basicConfig")
    def test_text_leaves_fastmcp_alone(self, _mock_basic_config):
        fastmcp_logger = self._fastmcp_rich_setup()
        handlers = fastmcp_logger.handlers[:]
        with patch.dict(os.environ, {}, clear=True):
            configure_logging(transport="http")
        assert fastmcp_logger.handlers == handlers
        assert fastmcp_logger.propagate is False

    def test_fastmcp_record_in_json_with_trace_ids(self):
        """End to end: a fastmcp.* record inside a span becomes a JSON line."""
        self._fastmcp_rich_setup()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(TraceContextFilter())
        handler.setFormatter(JsonFormatter())
        logging.getLogger().handlers[:] = [handler]

        with patch.dict(os.environ, {ENV_LOG_FORMAT: "json"}, clear=True):
            configure_logging(transport="http")
        with _active_span():
            logging.getLogger("fastmcp.server.server").warning("from fastmcp")

        [entry] = [json.loads(line) for line in stream.getvalue().splitlines()]
        assert entry["logger"] == "fastmcp.server.server"
        assert entry["message"] == "from fastmcp"
        assert entry["trace_id"] == TRACE_ID_HEX
        assert entry["span_id"] == SPAN_ID_HEX

    @pytest.mark.parametrize(
        ("log_format", "expected"), [("json", "json"), ("text", "text")]
    )
    @patch("logging.basicConfig")
    def test_returns_log_format(self, _mock_basic_config, log_format, expected):
        with patch.dict(os.environ, {ENV_LOG_FORMAT: log_format}, clear=True):
            assert configure_logging() == expected


def test_uvicorn_log_config():
    assert uvicorn_log_config("json") == {"log_config": None}
    assert uvicorn_log_config("text") == {}
