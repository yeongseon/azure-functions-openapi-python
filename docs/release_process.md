# Release Process

This document describes how a new version of **azure-functions-openapi** reaches PyPI.

Releases are automated by [Release Please](https://github.com/googleapis/release-please). It decides the
version, writes the changelog, and cuts the tag. It does **not** publish — publication is a separate,
gated step.

---

## Who owns what

| Component | Owns |
|---|---|
| `release-please.yml` | version calculation, `CHANGELOG.md`, the Release PR, the tag, the GitHub Release |
| `release-please.yml` → `standardize-release-notes` | presentation of the GitHub Release body only (layout + credits, see [Release notes layout](#release-notes-layout-and-credits)) |
| `e2e-azure.yml` | real-Azure certification of one exact commit |
| `publish-pypi.yml` | the only path that uploads to PyPI (automatic on `v*` tag push, with `workflow_dispatch` as its recovery path — see [Recovery](#recovery)) |

**Do not hand-edit** `src/azure_functions_openapi/__init__.py` version strings, `CHANGELOG.md`, or
`.release-please-manifest.json`. Release Please maintains all three.

---

## Step 1: Merge Conventional Commits

Version bumps are derived from commit messages on `main`:

| Commit | Bump |
|---|---|
| `fix:` | patch (`0.25.1` → `0.25.2`) |
| `feat:` | minor (`0.25.1` → `0.26.0`) |
| `feat!:` / `fix!:` / `BREAKING CHANGE:` footer | minor while pre-1.0 (see below) |

While this package is pre-1.0, `bump-minor-pre-major` is enabled, so a breaking change moves to the
next minor (`0.26.0`) rather than jumping to `1.0.0`. Going to 1.0 is a deliberate, separate decision.

Use scopes for more context: `fix(openapi): preserve explicit 200 response`

### Changelog categories

| Prefix | Changelog section |
|--------|--------------------|
| `feat:` | Features |
| `fix:` | Bug Fixes |
| `docs:` | Documentation |
| `refactor:` | Refactor |
| `style:` | Styling |
| `test:` | Testing |
| `perf:` | Performance |
| `ci:` / `chore:` | Miscellaneous Tasks |
| `build:` | Other |

These are configured in `release-please-config.json` under `changelog-sections`.

---

## Step 2: Merge the Release PR

Release Please keeps an open **Release PR** titled like `chore(main): release 0.26.0`. It contains the
version bump and the changelog entry.

Merging that PR is the act of cutting a release. On merge, Release Please tags the release commit
(`v0.26.0`) and publishes the GitHub Release.

Release Please runs with `RELEASE_PLEASE_TOKEN` (a fine-grained PAT) rather than the default
`GITHUB_TOKEN`, so the required status checks run on the Release PR and it is merged under the same
branch-protection rules as any other PR. The PAT expires; regenerate it and update the secret before
it does, or no Release PR will appear.

---

## Release cadence

The maintainer, not the presence of an open Release Please PR, decides when
to ship. For a primarily solo-maintained library, **the default is to batch
routine user-facing changes into no more than one planned release per week**.
There is no required weekly release: skip an empty week or postpone a change
that is not ready. Merge ordinary `feat` / `fix` PRs to `main` as they pass
review; Release Please keeps the single release candidate up to date until
the maintainer explicitly chooses to merge it.

**Exceptions:** release sooner to fix a genuinely urgent security issue, a
production-breaking regression, or a failed release candidate that needs
a fix-forward patch. Explain the affected users and the exceptional timing
in the Release PR. Do not delay an urgent fix solely to obey the default
weekly interval.

Before merging a routine Release PR, the maintainer checks:

- What materially changed for package users, and whether multiple ready
  changes can be shipped together.
- The latest **actually published PyPI version** and any failed or unpublished
  GitHub Release candidate; GitHub Release creation is not proof of a PyPI upload.
- Breaking changes, upgrade instructions, and whether release-specific
  cookbook/Azure certification gates are expected to pass.
- Whether a known near-term correction should be included to avoid an
  unnecessary follow-up patch.

**Do not** auto-merge Release PRs, create time-triggered tags, bypass
tag-specific verification, or move already-created tags. Release Please still
owns all version numbers, tags, Release PRs and `CHANGELOG.md`. This is a
small, human-review timing rule, not a new automated release system.

---

## Step 3: The release workflow runs

The tag starts `publish-pypi.yml`. Everything else is automatic:

```
build -> lib-tests -> cookbook-smoke -> cookbook-host-smoke -> azure-e2e -> publish
```

| Tier | Catches |
|---|---|
| `build` | tag/`__version__` mismatch; produces the one artifact that gets uploaded |
| `lib-tests` | library unit regressions |
| `cookbook-smoke` | downstream import/registration drift |
| `cookbook-host-smoke` | candidate wheel installs and a real `func` host + Azurite boots with it |
| `azure-e2e` | cloud-only drift — deploys to real Azure and runs the live e2e suite |
| `publish` | uploads the exact artifact `build` produced; never rebuilds |

`azure-e2e` calls `e2e-azure.yml` as a reusable workflow at the same ref being published, so
certification covers the exact published commit by construction. There is no separate certification
step to dispatch and no freshness window to expire.

Publication uses PyPI Trusted Publishing (OIDC); there is no API token to manage.

To re-run after a failed gate (nothing was uploaded, so the version is still free), use this only
to retry the **same unchanged** tagged candidate after an external or transient failure (a flaky
Azure deploy, a PyPI outage, a runner hiccup). `workflow_dispatch` takes **no inputs** — the
workflow reads the version to verify from `github.ref_name`, so the dispatch **ref** must be the
existing tag itself:

```bash
gh workflow run publish-pypi.yml --ref v0.26.0
```

Do not pass `--ref main` with a `-f tag=...` input: that input does not exist, and dispatching
against `main` would compare the package version against the literal ref name `main` and fail the
check even if the input were accepted. If the failure instead requires a code or workflow
correction, fix forward on `main` and let the next Release PR cut a new version — never move or
reuse a tag to make a changed commit appear to be the same release candidate.

---


## Release notes layout and credits

After Release Please creates the GitHub Release, the `standardize-release-notes` job rewrites
**only the Release body** with `tools/release_notes.py`. It does not create or move tags, does not
edit `CHANGELOG.md`, and runs separately from `publish-pypi.yml`, so it cannot block a release.
The items are the ones Release Please already generated, so the Release and `CHANGELOG.md` list
the same changes. The tool refuses to write if a PR or commit reference would be dropped.

Layout (empty sections are omitted; short owner-only patches can contain only a
single fix entry and the Full Changelog link):

1. `## vX.Y.Z (YYYY-MM-DD)`
2. Notes: status annotations such as "not published to PyPI"
3. Highlights
4. Breaking Changes, followed by the upgrade steps
5. Features, Bug Fixes, Performance, Reverts
6. New Contributors
7. A collapsed block for documentation, maintenance and other changes (historical releases only,
   because Release Please hides those types)
8. `**Full Changelog**` compare link

Credit rules:

- The project is primarily solo-maintained. For changes authored or co-authored by
  the repository owner (`owner_login` in `.github/release-notes.json`, currently `@yeongseon`),
  **do not append `by @yeongseon`**. PR/commit references remain visible.
- External human contributors are credited with `by @username` after verifying the merged
  PR author, commit author, or a `Co-authored-by` trailer with a GitHub
  `<id>+<login>@users.noreply.github.com` address. A maintainer squash-merge does not
  erase attribution to an external PR author. Nothing is guessed.
- Bots (`[bot]`, `app/…`) and the logins in `non_human_logins` of `.github/release-notes.json`
  are never credited.
- **New Contributors** appears only for a verified first merged contribution by an
  **external human**. It is omitted entirely in owner-only releases.

Release-specific statements that must never be lost (for example a release that was not
published) are listed under `protected` in `.github/release-notes.json`; the tool fails instead of
dropping them.

```bash
# Needs a token: export GH_TOKEN=$(gh auth token)
# Preview without changing anything
python3 -m tools.release_notes apply v0.31.0 --dry-run
# Re-render an already standardized release (it is skipped otherwise)
python3 -m tools.release_notes apply v0.31.0 --force --backup ./release-backup
```

Editing a historical Release never republishes a package and never touches the tag.

---

## What is no longer used

| Retired | Replacement |
|---|---|
| `make release-patch` / `release-minor` / `release-major` / `release` | merge the Release PR |
| `make changelog` / `make commit-changelog` (git-cliff) | Release Please writes `CHANGELOG.md` |
| `make tag-release` | Release Please creates the tag |
| `make publish-pypi` (local `hatch publish`) | the `publish` job in `publish-pypi.yml` |
| `cliff.toml` | `release-please-config.json` |
| manual Azure certification dispatch | the `azure-e2e` job in `publish-pypi.yml` |

These Makefile targets are **deleted**, not merely discouraged, so nothing can create a second writer
for the version, changelog, or tags — or push an ungated artifact to PyPI.

`make publish-test` (TestPyPI) is unaffected.

---

## Recovery

| Situation | Action |
|---|---|
| Any gate failed | Nothing was uploaded. For an external/transient failure, re-run the *same unchanged* tag with `gh workflow run publish-pypi.yml --ref vX.Y.Z` (no inputs — see [Step 3](#step-3-the-release-workflow-runs) for why `--ref main -f tag=...` does not work). For a failure that needs a code or workflow correction, fix forward on `main` and let the next Release PR cut a new version instead. Never move or reuse a tag. |
| Tag exists but was never published | A valid resting state. Re-run publish, or abandon the version and let the next release take the following number. |
| Release PR stopped appearing | Check for a stale `autorelease: pending` label on an already-merged Release PR. Release Please treats that as a release in flight and will not open another. This failure is silent — the workflow still reports success. |
| Automation unavailable (break-glass) | Bump `__version__`, match `.release-please-manifest.json`, commit, tag, push. The tag starts the same gated workflow — never bypass it. |
| Release audit reports a discrepancy | Run `make release-audit` (set `GH_TOKEN`). Never move, delete or re-create a tag to make it pass. A new tag that declares another version, or is not on `main`, is a failed release candidate: fix forward with the next release. A published version without a tag or Release is recorded in [Release History](release_history.md) and `.github/release-audit.json`, with evidence. |

Historical cases where a tag, a GitHub Release and a PyPI distribution do not line up (an invalid
tag, a published version without a tag, tag-only versions) are recorded in
[Release History](release_history.md). A GitHub Release is not proof of publication: use PyPI.

---

## Still-current Makefile commands

| Task | Command |
|------|---------|
| Build distributions | `make build` |
| Publish to TestPyPI | `make publish-test` |
| Show current version | `make version` |

To test a local build:

```bash
pip install dist/azure_functions_openapi-<version>-py3-none-any.whl
```

---

## Related

- [CHANGELOG.md](https://github.com/yeongseon/azure-functions-openapi-python/blob/main/CHANGELOG.md)
- [Development Guide](development.md)
- [Contributing](contributing.md)
- [Release Please](https://github.com/googleapis/release-please)
