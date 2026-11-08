# Integration Fixtures

These fixtures are used by the CI `integration-test` stage
(see `.github/workflows/ci.yml` and `scripts/ci/docker-startup-check.sh`)
and by `tests/test_component_fixtures.py`.
They are independent of the unit-test fixtures in the parent directory —
changes to `tests/fixtures/sample_*.yaml` do not affect these files and
vice versa.

## Files

| File | Purpose |
|---|---|
| `aas-repo-official-spec.yaml` | Official Asset Administration Shell Repository Service spec, `AssetAdministrationShellRepositoryServiceSpecification/V3.1_SSP-001.yaml` |
| `submodel-repo-official-spec.yaml` | Official Submodel Repository Service spec, `SubmodelRepositoryServiceSpecification/V3.1_SSP-001.yaml` |
| `aas-registry-official-spec.yaml` | Official Asset Administration Shell Registry Service spec, `AssetAdministrationShellRegistryServiceSpecification/V3.1_SSP-001.yaml` |
| `submodel-registry-official-spec.yaml` | Official Submodel Registry Service spec, `SubmodelRegistryServiceSpecification/V3.1_SSP-001.yaml` |
| `concept-description-repo-official-spec.yaml` | Official Concept Description Repository Service spec, `ConceptDescriptionRepositoryServiceSpecification/V3.1_SSP-001.yaml` |
| `config.yaml.template` | Shared config declaring all five components, each pointing at its fixture spec under `/app/spec/`. |

## Source

All five specs are the official IDTA-01002 specs from tag
[`v3.1.3`](https://github.com/admin-shell-io/aas-specs-api/tree/v3.1.3) of
`admin-shell-io/aas-specs-api`, bundled into self-contained files: the
external `$ref`s to the Part 1 / Part 2 schemas are moved into
`components`; the content is otherwise unchanged.

© Industrial Digital Twin Association (IDTA), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
(see `REUSE.toml` and `LICENSES/CC-BY-4.0.txt`).

To regenerate them, or to switch to another tag (needs git, perl and npx):

```bash
scripts/ci/update-integration-fixtures.sh v3.1.3
```

When the tag changes, update the expected tools in
`tests/test_component_fixtures.py` and the tag in this README.

## Local usage

```bash
# Build the image once
docker build -t aas-mcp-server:test .

# Run the startup check for any component
scripts/ci/docker-startup-check.sh aas-repo \
  tests/fixtures/integration/config.yaml.template \
  tests/fixtures/integration/aas-repo-official-spec.yaml
```
