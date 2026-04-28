# Contributing to AAS MCP Server

## Code of Conduct

All contributors must abide by the [SAP Open Source Code of Conduct](https://github.com/SAP/.github/blob/main/CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to ospo@sap.com.

## How to Contribute

### Reporting Issues

Before creating an issue, please check if a similar issue already exists. When creating a new issue:

1. Use a clear and descriptive title
2. Provide detailed steps to reproduce the problem
3. Include relevant details about your configuration and environment
4. Add code samples or test cases if applicable

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion:

1. Use a clear and descriptive title
2. Provide a detailed description of the proposed functionality
3. Explain why this enhancement would be useful
4. Include examples of how the feature would be used

### Contributing Code

We welcome code contributions! Please follow this process:

1. **Check existing issues** - Before starting work, create a GitHub issue describing the problem or enhancement
2. **Claim the issue** - Comment on the issue to indicate you're working on it
3. **Wait for feedback** - Maintainers will review and may provide guidance
4. **Fork and create a branch** - Create a descriptive branch name (e.g., `fix/auth-token-handling` or `feat/add-registry-support`)
5. **Make your changes** - Follow our coding standards (see below)
6. **Write tests** - Ensure your changes are covered by tests
7. **Update documentation** - Update README.md and other docs as needed
8. **Submit a pull request** - Reference the issue number in your PR description

### Developer Certificate of Origin (DCO)

Due to legal reasons, contributors will be asked to accept a Developer Certificate of Origin (DCO) on their first pull request. This is managed automatically through a GitHub bot. We use the [standard DCO text of the Linux Foundation](https://developercertificate.org/).

## Development Setup

### Prerequisites

- Python 3.12 or higher
- `uv` package manager (recommended) or `pip`

### Installation

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/aas-mcp-server.git
cd aas-mcp-server

# Install in editable mode with development dependencies
pip install -e ".[dev]"

# Or using uv
uv pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=aas_mcp_server --cov-report=html

# Run specific test file
pytest tests/test_openapi_loader.py -v

# Run specific test
pytest tests/test_openapi_loader.py::TestFilterPaths::test_filter_single_path_all_methods -v
```

### Testing Locally

```bash
# Test with MCP Inspector (interactive browser UI)
./scripts/run_inspector.sh

# Test specific component
AAS_COMPONENT=submodel-repo ./scripts/run_inspector.sh

# Test with custom backend
AAS_BASE_URL=http://localhost:8081 ./scripts/run_inspector.sh
```

## Coding Standards

### Python Style

- Follow [PEP 8](https://pep8.org/) style guide
- Use type hints for function parameters and return values
- Maximum line length: 100 characters
- Use meaningful variable and function names

### Code Organization

- Keep functions focused and single-purpose
- Add docstrings to all public functions and classes
- Use module-level docstrings to explain file purpose
- Group related functionality into modules

### Documentation

- Update README.md for user-facing changes
- Update CLAUDE.md for architecture or development workflow changes
- Add docstrings to new functions and classes
- Include examples in docstrings where helpful

### Commit Messages

We follow [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

**Types:**
- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks

**Examples:**
```
feat(openapi-loader): add support for runtime path filtering

fix(tool-curation): correct allowlist filtering logic

docs(readme): update installation instructions

test(openapi-loader): add tests for overlay application
```

## Testing Guidelines

### Test Coverage

- Write tests for all new functionality
- Maintain or improve existing test coverage
- Include both unit tests and integration tests

### Test Structure

- Use descriptive test names: `test_<what_is_being_tested>`
- Use fixtures for common test setup
- Keep tests focused on one behavior
- Use parametrize for testing multiple inputs

### Test Example

```python
def test_filter_single_path_all_methods(self, sample_openapi_spec):
    """Test filtering a single path with all methods included."""
    filter_paths = ["/shells"]
    
    result = filter_openapi_spec(sample_openapi_spec, filter_paths)
    
    assert "/shells" in result["paths"]
    assert len(result["paths"]) == 1
```

## Adding Support for New Implementations

To add support for a new AAS implementation (e.g., Eclipse BaSyx, FA³ST Service):

1. **Document endpoints** - Create `docs/your-impl-endpoints.json` with the implementation's supported endpoints
2. **Create configuration** - Copy `configs/config.yaml.template` to `configs/your-impl-config.yaml`
3. **Generate derived specs** - Run `python3 scripts/generate_implementation.py --config configs/your-impl-config.yaml`
4. **Test thoroughly** - Use MCP Inspector to verify all tools work correctly
5. **Submit PR** - Include configuration, derived specs, and documentation

## AI-Generated Code

If you use AI tools (GitHub Copilot, ChatGPT, etc.) to generate code:

- You must review and understand all AI-generated code
- Ensure AI-generated code follows our coding standards
- Test AI-generated code thoroughly
- Follow [SAP's guidelines on AI-generated code](https://github.com/SAP/.github/blob/main/CONTRIBUTING_USING_GENAI.md)

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.

## Questions?

If you have questions about contributing:

1. Check existing issues and discussions
2. Create a new issue with your question
3. Reach out to maintainers through GitHub

## Recognition

Contributors will be acknowledged in:
- GitHub's contributor graph
- Release notes for significant contributions

Thank you for contributing to AAS MCP Server! 🎉
