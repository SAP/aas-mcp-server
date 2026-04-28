# Test Fixtures

This directory contains test data files used by the integration test suite.

## Files

### OpenAPI Specifications

- **`sample_official_spec.yaml`**
  - Minimal official AAS Repository specification
  - Contains 6 operations across 3 paths
  - Used to test spec intersection and overlay application
  - Represents the "complete" AAS specification

- **`sample_implementation_spec.yaml`**
  - Implementation-specific spec showing partial support
  - Contains 5 operations (subset of official spec)
  - Missing: `/shells/{aasIdentifier}/asset-information` endpoint
  - Used to test spec intersection logic

### Overlays

- **`sample_overlay.yaml`**
  - OpenAPI Overlay specification for renaming operations
  - Renames operationIds to be more LLM-friendly
  - Examples:
    - `GetAllAssetAdministrationShells` → `list_shells`
    - `PostAssetAdministrationShell` → `create_shell`
    - `GetAssetAdministrationShellById` → `get_shell`

## Usage

These fixtures are loaded by pytest fixtures in `test_integration_comprehensive.py`:

```python
@pytest.fixture
def sample_official_spec(test_fixtures_dir):
    """Load official AAS Repository spec from fixture file."""
    with open(test_fixtures_dir / "sample_official_spec.yaml") as f:
        return yaml.safe_load(f)
```

## Test Scenarios

1. **Spec Intersection Testing**
   - Official spec (6 paths) ∩ Implementation spec (5 paths) = Derived spec (5 paths)
   - Validates that only supported operations are exposed

2. **Overlay Application Testing**
   - Verifies operationIds are renamed correctly
   - Verifies summaries are updated correctly

3. **Complete Pipeline Testing**
   - Config → Load specs → Intersection → Overlay → Curation → MCP Server

## Adding New Fixtures

To add new test data:

1. Create a new YAML file in this directory
2. Add a pytest fixture to load it in the test file
3. Document it in this README

Example:
```python
@pytest.fixture
def my_new_fixture(test_fixtures_dir):
    """Load my test data."""
    with open(test_fixtures_dir / "my_fixture.yaml") as f:
        return yaml.safe_load(f)
```
