# Integration Fixtures

These fixtures are used **only** by the CI `integration-test` stage
(see `.github/workflows/ci.yml` and `scripts/ci/docker-startup-check.sh`).
They are independent of the unit-test fixtures in the parent directory —
changes to `tests/fixtures/sample_*.yaml` do not affect these files and
vice versa.

## Files

| File | Purpose |
|---|---|
| `aas-repo-official-spec.yaml` | Fixture for the `aas-repo` component. **Hand-authored** in the style of `tests/fixtures/sample_official_spec.yaml`. |
| `submodel-repo-official-spec.yaml` | Fixture for the `submodel-repo` component. **Derived** by manual chunking from an official IDTA Submodel Repository OpenAPI spec (not committed to this repo — see [aas-specs](https://github.com/admin-shell-io/aas-specs/tree/main/schemas/openapi)). |
| `aas-registry-official-spec.yaml` | Fixture for the `aas-registry` component. **Derived** from an official IDTA AAS Registry OpenAPI spec (same source). |
| `submodel-registry-official-spec.yaml` | Fixture for the `submodel-registry` component. **Derived** from an official IDTA Submodel Registry OpenAPI spec (same source). |
| `config.yaml.template` | Shared config declaring all four components, each pointing at its fixture spec under `/app/spec/`. |

## Chunking rule (for the three derived fixtures)

The real official specs are too large (up to ~143 KB / ~3900 lines) to feed
into a Docker startup smoke test, so each derived fixture is a hand-picked
subset of the source spec:

- ~3–5 representative endpoints
- At least one `GET` operation
- At least one path with a path parameter (`{...}`)
- Referenced schemas inlined or trimmed to only what those endpoints need
- Original `operationId`s from the source spec are preserved
- Aim for ~50–100 lines; hard ceiling of 200 lines
- Must be a valid standalone OpenAPI 3.0 or 3.1 document
  (parses with `yaml.safe_load`, has top-level `openapi`, `info.title`,
  `info.version`, and non-empty `paths`)

To refresh a fixture, re-download the corresponding official spec from the
[aas-specs repository](https://github.com/admin-shell-io/aas-specs/tree/main/schemas/openapi)
and repeat the chunking process above.

## Local usage

```bash
# Build the image once
docker build -t aas-mcp-server:test .

# Run the startup check for any component
scripts/ci/docker-startup-check.sh aas-repo \
  tests/fixtures/integration/config.yaml.template \
  tests/fixtures/integration/aas-repo-official-spec.yaml
```
