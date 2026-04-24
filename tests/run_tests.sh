#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SAP SE or an SAP affiliate company and aas-mcp-server contributors
# SPDX-License-Identifier: Apache-2.0

set -e

echo "======================================"
echo "AAS MCP Server - Full Test Suite"
echo "======================================"
echo ""

# Parse arguments
RUN_INTEGRATION=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --integration)
      RUN_INTEGRATION=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--integration]"
      exit 1
      ;;
  esac
done

# Step 1: Run unit tests
echo "Step 1/3: Running unit tests..."
echo "--------------------------------------"

# Check if pytest-cov is available
if uv run python -c "import pytest_cov" 2>/dev/null; then
  # Run with coverage
  uv run pytest tests/ \
    --ignore=tests/test_cli.py \
    --ignore=tests/test_server.py \
    --verbose \
    --cov=src/aas_mcp_server \
    --cov-report=term-missing \
    --cov-report=html \
    -m "not integration"
  COVERAGE_AVAILABLE=true
else
  # Run without coverage
  echo "WARNING  pytest-cov not installed, running without coverage"
  uv run pytest tests/ \
    --ignore=tests/test_cli.py \
    --ignore=tests/test_server.py \
    --verbose \
    -m "not integration"
  COVERAGE_AVAILABLE=false
fi

echo ""
echo "OK Unit tests passed!"
echo ""

# Step 2: Run integration tests (if requested)
if [ "$RUN_INTEGRATION" = true ]; then
  echo "Step 2/3: Running integration tests..."
  echo "--------------------------------------"

  # Check if backend is available on port 8081
  echo "Checking if backend is available on http://localhost:8081..."
  if curl -sf http://localhost:8081/shells > /dev/null 2>&1; then
    echo "OK Backend is available"
    echo ""
  else
    echo "ERROR Error: Backend is not available on http://localhost:8081"
    echo ""
    echo "Please start your AAS backend server on port 8081 before running integration tests."
    echo ""
    echo "For example, if using Eclipse BaSyx Docker:"
    echo "  docker run -p 8081:8081 eclipsebasyx/aas-environment:2.0.0"
    echo ""
    exit 1
  fi

  # Run integration tests
  if [ "$COVERAGE_AVAILABLE" = true ]; then
    uv run pytest tests/test_integration_comprehensive.py \
      --verbose \
      --run-integration \
      --cov=src/aas_mcp_server \
      --cov-report=term-missing \
      --cov-append
  else
    uv run pytest tests/test_integration_comprehensive.py \
      --verbose \
      --run-integration
  fi

  echo ""
  echo "OK Integration tests passed!"
  echo ""
else
  echo "Step 2/3: Skipping integration tests (use --integration to run)"
  echo ""
fi

# Step 3: Summary
echo "Step 3/3: Test Summary"
echo "--------------------------------------"
echo "OK Unit tests: PASSED"
if [ "$RUN_INTEGRATION" = true ]; then
  echo "OK Integration tests: PASSED"
else
  echo "SKIPPED  Integration tests: SKIPPED"
fi
echo ""
if [ "$COVERAGE_AVAILABLE" = true ]; then
  echo "Coverage report: htmlcov/index.html"
fi
echo ""
echo "======================================"
echo "All tests completed successfully! "
echo "======================================"
