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
| `config.yaml.template` | Shared config declaring all five components, each pointing at its spec under `/app/spec/`. |
| `specs/aas-repo-official-spec.yaml` | Generated. Official Asset Administration Shell Repository Service spec, `AssetAdministrationShellRepositoryServiceSpecification/V3.2_SSP-001.yaml` |
| `specs/submodel-repo-official-spec.yaml` | Generated. Official Submodel Repository Service spec, `SubmodelRepositoryServiceSpecification/V3.2_SSP-001.yaml` |
| `specs/aas-registry-official-spec.yaml` | Generated. Official Asset Administration Shell Registry Service spec, `AssetAdministrationShellRegistryServiceSpecification/V3.2_SSP-001.yaml` |
| `specs/submodel-registry-official-spec.yaml` | Generated. Official Submodel Registry Service spec, `SubmodelRegistryServiceSpecification/V3.2_SSP-001.yaml` |
| `specs/concept-description-repo-official-spec.yaml` | Generated. Official Concept Description Repository Service spec, `ConceptDescriptionRepositoryServiceSpecification/V3.2_SSP-001.yaml` |

## Source

The five specs are not part of this repository. CI generates them in its
workspace from the official IDTA-01002 specs at the tag pinned in
`scripts/ci/prepare-integration-specs.sh`
([`v3.2.0`](https://github.com/admin-shell-io/aas-specs-api/tree/v3.2.0) of
`admin-shell-io/aas-specs-api`), bundled into self-contained files: the
external `$ref`s to the Part 1 / Part 2 schemas are moved into
`components`; the content is otherwise unchanged. `specs/` is git-ignored.

© Industrial Digital Twin Association (IDTA), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

To move to a new upstream release, update `TAG` and `COMMIT` in the script
in a dedicated change, then update the expected tools in
`tests/test_component_fixtures.py` and the tag in this README.

## Local usage

```bash
# Generate the specs (needs git, perl and npx)
scripts/ci/prepare-integration-specs.sh

# Run the tests that build a server from them (skipped if the specs are missing)
pytest tests/ -m integration

# Build the image once
docker build -t aas-mcp-server:test .

# Run the startup check for any component
scripts/ci/docker-startup-check.sh aas-repo \
  tests/fixtures/integration/config.yaml.template \
  tests/fixtures/integration/specs/aas-repo-official-spec.yaml
```
