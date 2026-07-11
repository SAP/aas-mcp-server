# Releasing

This project uses a **two-track versioning model**:

| Track | Where | Who moves it | Purpose |
|-------|-------|--------------|---------|
| **Internal (dev)** | `pyproject.toml` | Auto-bumped on every merged PR via `version-bump.yml` | Day-to-day dev tracking |
| **Customer-facing (release)** | Git tag + Docker image tag | You type it manually when cutting a release | Public SemVer line |

The two tracks are **intentionally decoupled**: intermediate internal version numbers are never published as releases, and the public version you choose does not have to match `pyproject.toml`. This is safe because the project publishes a Docker image only.

---

## How to cut a release

1. Go to **Actions → Release → Run workflow**.
2. Enter the next public version in the `version` field — for example `0.2.0` — **without a leading `v`**.
3. Click **Run workflow**.

That's it. The workflow will:

- Validate the format (`X.Y.Z`) and enforce the **monotonic rule** (must be strictly greater than the last `v*` tag).
- Build and push a **multi-architecture image** (`linux/amd64` + `linux/arm64`) with **OCI standard labels** (title, description, source URL, version, license) — the versioned image is pushed **first** so it is immutable before the tag is created: `ghcr.io/sap/aas-mcp-server:<version>`
- Create and push tag `v<version>`.
- Publish a GitHub Release at `v<version>` with **auto-generated release notes** that bundle every PR merged since the previous release tag (categorized by label).
- Update `:latest` **last**, so a failure mid-run never moves `:latest` off the previous good release.

### Re-run safety

If the workflow fails after the tag is pushed (e.g. the release creation or `:latest` push fails), you can re-run it safely: the tag-creation and release-creation steps are idempotent — they detect the existing tag/release and skip, then continue with the remaining steps.

---

## Monotonic rule

The `version` input must be **strictly greater** than the most recent `v*` tag (sorted with `sort -V`, so `v0.10.0` > `v0.9.0`). You cannot reuse a tag that already exists on a different commit.

---

## CHANGELOG.md

`CHANGELOG.md` is **hand-maintained** (Keep-a-Changelog format). The auto-generated release notes on GitHub are separate from — and do not replace — `CHANGELOG.md`.

---

## One-time GHCR preflight (before the very first release)

Before running the first release, verify the following in the SAP org settings:

1. **Member package creation is enabled** for the intended visibility (public/internal). If disabled, the `GITHUB_TOKEN` push will fail with a 403.
2. **No pre-existing unlinked package** named `ghcr.io/sap/aas-mcp-server` exists. An unlinked package can block the first push or prevent auto-linking to the repo.
3. After the first successful push, set the package visibility and confirm it auto-linked to `SAP/aas-mcp-server` in **Packages** on the repo page.

These are org-settings issues, not workflow bugs — the workflow itself is correct.

---

## `:latest` is mutable

The `:latest` tag is updated on every release. **Production consumers should pin a specific version or digest**, not `:latest`:

```bash
# Pinned version (recommended)
docker pull ghcr.io/sap/aas-mcp-server:0.2.0

# Or pin to a digest for maximum immutability
docker pull ghcr.io/sap/aas-mcp-server@sha256:<digest>
```
