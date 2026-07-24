# Releasing aas-mcp-server

This document describes how to cut a release and how to complete the one-time SAP OSPO onboarding steps required before the container image and PyPI package can be published.

## How a release is cut

1. Merge a pull request to `main`. The `release.yml` workflow runs automatically.
2. **release-please** opens (or updates) a "Release PR" that bumps `pyproject.toml`, updates `CHANGELOG.md`, and proposes the next version.
3. A maintainer reviews and merges the Release PR.
4. release-please tags the commit and publishes a GitHub Release.
5. The `publish-docker` job runs automatically (gated by the `ghcr:aas-mcp-server` reviewer environment — a maintainer must approve the deployment).
6. The `publish-pypi` job is **disabled** until SAP OSPO/NAAS onboarding completes (see below).

> **Note on `release-as`:** The config currently pins the first release to `v0.1.0` via `"release-as": "0.1.0"` in `release-please-config.json`. Remove (or update) this key after the first Release PR is merged, otherwise all subsequent releases will also be pinned to `0.1.0`.

> **Note on same-run fan-out:** The publish jobs run in the same `release.yml` workflow gated on `release_created`, rather than in a separate `on: release: published` workflow. This is intentional: release-please creates the GitHub Release using `GITHUB_TOKEN`, which cannot trigger a separate `on: release` workflow (GitHub anti-recursion rule). The behaviour is functionally equivalent.

---

## One-time GHCR onboarding (required before first Docker push)

The `publish-docker` job pushes to `ghcr.io/SAP/aas-mcp-server`. Before the first push succeeds end-to-end, complete these steps:

### 1. Request a Docker MOMA entry
Open an issue in the SAP Open Source Outbound Request tracker and request a Docker(Hub) MOMA entry for this project. This is also used for GHCR.

### 2. Create the `ghcr:aas-mcp-server` GitHub environment
In the repository settings → Environments, create an environment named **`ghcr:aas-mcp-server`** with:
- **Required reviewers**: the repository admin team (an SAP employee must approve each release).

### 3. After the first push: OSPO package-settings validation
After the first image is pushed, contact the Open Source Program Office to validate the GHCR package settings:
- `Repository source` is correctly linked to this repository.
- `Manage Actions access` lists only this source repository with **Write** permissions (change from the default Admin if needed).
- `Inherited access` is checked and no additional members are listed.

### 4. Set package visibility to Public
Navigate to `https://github.com/orgs/SAP/packages/container/aas-mcp-server/settings` and set the package visibility to **Public** so unauthenticated users can pull the image.

---

## One-time PyPI onboarding (required before enabling the PyPI publish job)

The `publish-pypi` job is currently **disabled** (`false &&` guard in `release.yml`). It uses SAP's central PyPI account with OIDC Trusted Publishing — no stored token is needed. To enable it, complete the following 7-step SAP OSPO → NAAS → MOMA process:

> **Name-squatting note:** PyPI has no dedicated SAP namespace. The package name `aas-mcp-server` is already public in this repository (`pyproject.toml`), so the "don't disclose early" advice is moot here. If the name is ever squatted before the first release, contact ospo@sap.com.

### Step 1 — Project Team: request the release process
Open an issue in the SAP Open Source Outbound Request tracker providing:
- Link to this repository
- Desired package name: `aas-mcp-server`
- MOMA entry (if already exists)
- GitHub Actions workflow name: `release.yml`
- GitHub Actions environment name: `pypi:aas-mcp-server`
- PPMS FOSS Entry ID for this repository (create via your Outbound Processor if not yet available)

### Step 2 — OSPO: validate and assign
The Open Source Program Office validates the information and assigns **NAAS (Mobile & External Repository Assembly & Delivery)** to the issue.

### Step 3 — NAAS: create MOMA entry
NAAS creates (if not existing) a MOMA entry representing the package release and responds on the issue with the link.

### Step 4 — Project Team: fill MOMA metadata
Fill out the MOMA entry with:
- **Release License**: `Apache-2.0`
- **Release Builds**: `No`
- **Release Repository Root**: `https://pypi.org/project/aas-mcp-server`
- **Bug Tracking Component**: `https://github.com/SAP/aas-mcp-server/issues`
- **Link to DEV SCM-Repo**: `https://github.com/SAP/aas-mcp-server`
- **Link to Dev SCM-Repo Forked to NAAS**: `n/a`
- **PyPI Project Name**: `aas-mcp-server`
- **Copy of required license in package**: `yes`
- **METADATA in Delivery Package**: `yes`
- **SAP Internal Information is Excluded in Metadata**: `yes`

### Step 5 — NAAS: validate MOMA entry
NAAS validates the entry and responds on the issue.

### Step 6 — NAAS: create the PyPI project and configure the trusted publisher
NAAS creates the `aas-mcp-server` project on PyPI under the SAP central account and configures the Trusted Publisher with:
- **Owner**: `SAP`
- **Repository**: `aas-mcp-server`
- **Workflow**: `release.yml`
- **Environment**: `pypi:aas-mcp-server`

### Step 7 — Project Team: enable the publish job
Once NAAS confirms the trusted publisher is configured:

1. Create the **`pypi:aas-mcp-server`** GitHub environment in repository settings → Environments, with required reviewers (repo admin team).
2. In `.github/workflows/release.yml`, remove the `false &&` from the `publish-pypi` job's `if:` condition:
   ```yaml
   # Before (disabled):
   if: ${{ false && needs.release-please.outputs.release_created == 'true' }}
   # After (enabled):
   if: ${{ needs.release-please.outputs.release_created == 'true' }}
   ```
3. Commit and push. The next release will publish to PyPI automatically.
