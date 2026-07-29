# Releasing aas-mcp-server

This document describes how to cut a release and how to complete the one-time SAP OSPO onboarding steps required before the container image and PyPI package can be published.

## How a release is cut

The `release.yml` workflow is triggered **manually** via `workflow_dispatch` (Actions tab → Release → Run workflow). It does NOT run automatically on push to `main`.

1. Run the **Release** workflow manually (`workflow_dispatch`). **release-please** opens (or updates) a "Release PR" that bumps `pyproject.toml`, updates `CHANGELOG.md`, and proposes the next version.
2. A maintainer reviews and merges the Release PR.
3. Run the **Release** workflow manually again (or it fires automatically if you add a `push` trigger). release-please detects the merged Release PR, tags the commit, and publishes a GitHub Release.
4. The `publish-docker` job runs (gated by the `ghcr:aas-mcp-server` reviewer environment — a maintainer must approve the deployment).
5. The `publish-pypi` job is **enabled** via OIDC Trusted Publishing (gated by the `pypi:aas-mcp-server` reviewer environment — a maintainer must approve the deployment).

> **Note on the two-run flow:** The first `workflow_dispatch` opens (or updates) the Release PR — Docker and PyPI publishing do NOT run on this first dispatch. Publishing only runs on the second run (second time) after merge of the Release PR.

> **Note on GITHUB_TOKEN and CI on Release PRs:** release-please opens the Release PR using `GITHUB_TOKEN`. GitHub's anti-recursion rule means that PRs created by `GITHUB_TOKEN` do not automatically trigger CI workflows. If branch protection requires passing checks before merge, you may need to close and reopen the Release PR, or push an empty commit to it, to trigger CI. Alternatively, a GitHub App token or PAT can be used instead of `GITHUB_TOKEN` to bypass this limitation.

> **Note on `release-as`:** The config currently pins the first release to `v0.1.0` via `"release-as": "0.1.0"` in `release-please-config.json`. Remove (or update) this key after the first Release PR is merged, otherwise all subsequent releases will also be pinned to `0.1.0`.

> **Post-first-release checklist:** After the first Release PR merges and the release is published, remove `"release-as": "0.1.0"` from `release-please-config.json` (and confirm the manifest advanced to the next version). If this is not done, all subsequent releases will re-attempt version `0.1.0` and the PyPI publish step will hard-fail on version collision.

> **Note on same-run fan-out:** The publish jobs run in the same `release.yml` workflow gated on `release_created`, rather than in a separate `on: release: published` workflow. This is intentional: release-please creates the GitHub Release using `GITHUB_TOKEN`, which cannot trigger a separate `on: release` workflow (GitHub anti-recursion rule). The behaviour is functionally equivalent.

---

## One-time GHCR onboarding (required before first Docker push)

The `publish-docker` job pushes to `ghcr.io/sap/aas-mcp-server`. Before the first push succeeds end-to-end, complete these steps:

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

## PyPI publish troubleshooting

### Partial upload
`skip-existing` is `false` (the default). If a publish partially succeeds (e.g. the sdist uploads but the wheel fails mid-transfer), a re-run will fail because PyPI does not allow re-uploading a filename once it has been accepted — **deleting the file from the PyPI project page does not help**, as the filename remains permanently reserved.

Two recovery options:

1. **Set `skip-existing: true`** in the `Publish to PyPI` step before re-running. This skips already-uploaded files and uploads only the missing ones. Remove the flag again after the release.
2. **Cut a new version** (e.g. a post-release `0.1.0.post1`) if the already-uploaded artifact itself is bad and needs to be replaced.

### `release-as` version collision
If `"release-as"` is still set in `release-please-config.json` after the first release, every subsequent release will attempt to publish the same version and fail. See the post-first-release checklist above.

---

## One-time PyPI onboarding (Completed)

The `publish-pypi` job is now **enabled** via OIDC Trusted Publishing using SAP's central PyPI account — no stored token is needed. The following 7-step SAP OSPO → NAAS → MOMA onboarding process has been completed and is preserved here for reference:

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
