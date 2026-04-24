# Testing Guide

## Quick Start

```bash
# Run all tests (excluding backend integration)
uv run pytest

# Run with coverage
uv run pytest --cov=src/aas_mcp_server --cov-report=term-missing

# Run integration tests (requires backend on localhost:8081)
uv run pytest --run-integration
```

## Test Organization

### Unit Tests
- **`test_cli.py`** - CLI argument parsing and validation
- **`test_config.py`** - Configuration loading and validation
- **`test_spec_processor.py`** - Spec intersection and overlay logic
- **`test_tool_curation.py`** - Allowlist filtering and curation
- **`test_wildcard_allowlist.py`** - Wildcard pattern matching
- **`test_openapi_loader.py`** - OpenAPI spec loading
- **`test_http_client.py`** - HTTP client building
- **`test_logging.py`** - Logging configuration
- **`test_server.py`** - MCP server construction

### Integration Tests
- **`test_integration_comprehensive.py`** - End-to-end pipeline tests
  - Spec intersection (official ∩ implementation)
  - Overlay application
  - Curation (allowlist + aliases)
  - MCP server building
  - Backend connectivity (optional)

## Running Specific Tests

```bash
# Run a specific test file
uv run pytest tests/test_integration_comprehensive.py -v

# Run a specific test class
uv run pytest tests/test_integration_comprehensive.py::TestSpecIntersection -v

# Run a specific test method
uv run pytest tests/test_integration_comprehensive.py::TestSpecIntersection::test_intersection_basic -v

# Run tests matching a pattern
uv run pytest -k "intersection" -v
```

## Integration Tests with Backend

Integration tests require AAS backend services running on `localhost:8081`.

### Running Integration Tests

**Prerequisites:** Start your AAS backend server on port 8081 before running integration tests.

Example with Eclipse BaSyx Docker:
```bash
docker run -d -p 8081:8081 eclipsebasyx/aas-environment:2.0.0
```

Then run integration tests:
```bash
# Using the test script
./scripts/run_tests.sh --integration

# Or directly with pytest
uv run pytest --run-integration -v
```

The test script will check if the backend is available and fail with a helpful error message if it's not running.

## CI/CD Pipeline

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs:

1. **Unit Tests** - All tests without `--run-integration`
   - Python 3.12 and 3.13
   - Coverage reporting to Codecov

2. **Integration Tests** - With Eclipse BaSyx backend
   - Uses GitHub Actions service containers
   - Runs on Python 3.12
   - Tests complete pipeline with real backend

3. **Linting** - Code quality checks
   - Ruff (linter and formatter)
   - Mypy (type checking)

4. **Docker Build** - Verifies Docker image builds and runs

## Test Fixtures

Test fixtures are defined in:
- **`tests/conftest.py`** - Shared fixtures and pytest configuration
- **Individual test files** - Test-specific fixtures

Common fixtures:
- `sample_official_spec` - Minimal official AAS spec
- `sample_implementation_spec` - Implementation-specific spec
- `sample_overlay` - OpenAPI overlay for renaming
- `backend_available` - Checks if backend is running

## Coverage

```bash
# Generate HTML coverage report
uv run pytest --cov=src/aas_mcp_server --cov-report=html

# Open in browser
open htmlcov/index.html
```

## Debugging Tests

```bash
# Run with verbose output and stop on first failure
uv run pytest -vv -x

# Show print statements
uv run pytest -s

# Drop into debugger on failure
uv run pytest --pdb

# Show slowest tests
uv run pytest --durations=10
```

## Test Matrix

The CI/CD pipeline tests multiple configurations:

| Test Type | Python | Backend | Coverage |
|-----------|--------|---------|----------|
| Unit | 3.12, 3.13 | No | Yes |
| Integration | 3.12 | BaSyx 2.0 | Yes |
| Docker | 3.12 | No | No |

## Writing Tests

### Test Naming Convention
- Test files: `test_*.py`
- Test classes: `Test*`
- Test functions: `test_*`

### Example Test Structure

```python
class TestMyFeature:
    """Test MyFeature functionality."""

    def test_basic_case(self):
        """Test basic use case."""
        # Arrange
        input_data = {...}

        # Act
        result = my_function(input_data)

        # Assert
        assert result == expected_output

    def test_edge_case(self):
        """Test edge case handling."""
        ...
```

### Integration Test Guidelines

1. Mark tests that require backend with `request.config.getoption("--run-integration")`
2. Use `pytest.skip()` when backend is unavailable
3. Set reasonable timeouts (5s default)
4. Handle both 200 and 404 responses (empty backends)
5. Clean up any test data created

## Troubleshooting

### Tests Fail Locally But Pass in CI

- Check Python version: `python --version`
- Update dependencies: `uv sync`
- Clear pytest cache: `rm -rf .pytest_cache __pycache__`

### Integration Tests Timeout

- Check backend is running: `curl http://localhost:8081/shells`
- Check Docker containers: `docker ps`
- Increase timeout in test fixtures

### Import Errors

- Reinstall package: `uv sync`
- Check you're using uv: `which pytest` should show `.venv/bin/pytest`
