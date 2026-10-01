# AGENTS.md

## Purpose
`azure-functions-openapi` provides OpenAPI generation and validation support for Python Azure Functions.

## Repository Identity

- Project: `azure-functions-openapi`
- Project type: Python library
- Runtime scope: Azure Functions Python v2 programming model
- Minimum supported Python: `3.11`
- Packaging: `pyproject.toml` with Hatch

## Root vs Docs

Use the repository root for engineering and planning documents:

- `AGENTS.md`: contribution and automation rules
- `DESIGN.md`: architecture and design principles
- `PRD.md`: product scope and user-facing goals

Use `docs/` for user-facing documentation only:

- installation
- usage
- API reference
- examples
- diagnostics and guides

If a change materially affects behavior, architecture, or project positioning, update the
relevant root document in the same pull request or commit series.

## Read First
- `README.md`
- `CONTRIBUTING.md`
- `docs/agent-playbook.md`

## Working Rules

### Test Coverage
- Maintain test coverage at **95% or above** for committed changes and PRs.
- Run `hatch run pytest --cov --cov-report=term-missing -q` to verify before submitting changes.
- Any PR that drops coverage below 95% must include additional tests to compensate.
- Preserve the package's Python compatibility and public CLI behavior unless the change explicitly updates the contract.
- Keep documentation examples, generated schema expectations, and tests synchronized.
- Prefer focused changes inside the existing extension points.

### Documentation & Translations
- English (`README.md`) is the **canonical** source of truth for all documentation. Translated READMEs (`README.ko.md`, `README.ja.md`, `README.zh-CN.md`) are **best-effort**, community-maintained, and may lag the English source.
- Translation sync is **not** required in the same PR as an English change, and a PR is **never** blocked by translation drift. Update translations opportunistically; when you do, keep them faithful to the current English source.
- Each translated README carries a staleness banner linking back to the canonical English README. Keep that banner in place so readers always know the translation may be out of date.

## PR Workflow

**Always issue-first.** Before opening any PR:

1. Run `gh issue list` to check whether a tracking issue already exists for the change.
2. If no issue exists, create one following the Issue Conventions below before writing any code.
3. Open the PR only after the issue exists. The PR body **must** include `Closes #N` for every
   issue it resolves — never open a PR that cannot be traced back to an issue.

**Non-negotiable:** a PR without a linked issue will be rejected at review.

**No merge before the review checklist is complete.** Do not merge a PR until every item on its review checklist is checked off; an incomplete checklist blocks merge regardless of CI status.

### Who approves what

`main` requires a **pull request** (no direct pushes), every **required status check** green, and all conversations resolved. It requires **zero approving reviews**. `enforce_admins` is **false**.

**Why zero.** `yeongseon` is the only account with push access, GitHub forbids approving your own PR, and a second reviewer has been declined — that decision is settled; do not re-propose it as the preferred path. With one required approval, routine maintainer-authored work could only merge through an administrator bypass (#631). Dropping the count to 0 was the structural alternative #631 recorded; it was **adopted on 2026-09-28**. The required status checks and conversation resolution are what actually guard `main`, and they are unchanged.

**Review is still expected, just not enforced.** Read the diff before merging, including your own.

- **Split the work** when a change is genuinely reviewable by a contributor, so a second person authors it. That is the only path that produces a real second pair of eyes, and it is worth reaching for more often than it currently is.
- **An AI review is not an approval.** Copilot and Codex submit `COMMENTED`, never `APPROVED`. Treat "the AI reviewed it" and "a person accepted it" as separate facts.
- **Externally authored PRs** are reviewed by a maintainer before merging. Contributors have no push access, so they cannot merge their own PRs.

If a second maintainer ever gets push access, raise the approval count back to 1.

### Administrator bypass

With zero required approvals there is no routine reason to use `--admin`. **Never use it to skip a failing or pending required check** — that prohibition is absolute.

If a bypass is ever genuinely needed, the verification #631 introduced still applies:

- Fetch the required contexts (`gh api repos/{owner}/{repo}/branches/main/protection/required_status_checks --jq '.contexts[]?'`) and **diff them against the successful check-run names** on the head SHA. A required workflow that never started produces no check-run at all, so its absence is otherwise invisible.
- Query check-runs on the **exact head SHA being merged** (`gh api repos/{owner}/{repo}/commits/{sha}/check-runs`) and confirm zero non-success and zero incomplete. Do **not** read the PR status rollup: it can report a stale success. Two merges on 2026-09-27 broke `main` exactly this way (#628 here, `azure-functions-doctor-python`#463).
- Record the head SHA, the reason, the passing CI run, and anything left unverified in one PR comment. If the bypass does not meet these conditions, say so rather than reframing the change to fit.

Merge with `gh pr merge --admin --squash --delete-branch`.

### Dependabot

Dropping the approval count removed the only human gate on Dependabot auto-merge (#631 named this cost). It is absorbed by scoping auto-merge, not by accepting the loss:

- **`pip` patch/minor updates auto-merge** once every required check passes. Their risk is covered by the full test matrix.
- **`github-actions` updates never auto-merge.** A bumped action is pinned to a SHA, and the review that matters is confirming that SHA matches its claimed tag — CI cannot catch a wrong one. `dependabot-automerge.yml` enforces this by checking the package ecosystem.
- Major updates of either kind are not auto-merged.

Before merging an action update: confirm the diff is a version bump with no unrelated changes, and that each pinned SHA matches its claimed tag (`git ls-remote --tags <repo>`, comparing against the dereferenced `^{}` commit).

### Release flow

Releases go through a PR like everything else: Release Please maintains a **Release PR**, and merging it is what cuts the release. The old `make release-*` path, which pushed straight to `main`, is deleted.

Release Please runs with `secrets.RELEASE_PLEASE_TOKEN`, a fine-grained PAT, instead of the default `GITHUB_TOKEN`, so the required status checks run on the Release PR and the release tag starts `publish-pypi.yml`. The Release PR is merged under exactly the same rules as any other PR. See "Release Process" below.

## Issue Conventions

Follow these conventions when opening issues so the backlog stays consistent with sibling DX Toolkit repositories.

### Title

Titles for issues, pull requests, and commits follow the **Title Convention** in [`CONTRIBUTING.md`](CONTRIBUTING.md#title-convention), the single source of truth for the format and the allowed types.

### Body

Use the following sections, in order, omitting any that do not apply:

```
## Context
What problem this issue addresses and why now. Note the target release (e.g. vX.Y.Z) here if known.

## Acceptance Checklist
- [ ] Concrete, verifiable items.

## Out of scope
- Items intentionally excluded, with links to the issues that track them.

## References
- PRs, ADRs, sibling issues, external docs.
```

### Labels

- Apply at least one of `bug`, `enhancement`, `documentation`, `chore`.
- Apply exactly one priority label. The scale in use is `priority:critical` / `priority:high` / `priority:medium` / `priority:low`; `critical` is reserved for defects that reach package users, such as a broken published artifact or wrong product output.
- Labels are applied by maintainers or authorized triage automation. An external contributor without label permissions should describe urgency in the issue body and leave labelling to triage.
- Add `area:*` labels when they exist in the repository.
- Use `blocker` only when the issue blocks a release.

### Umbrella issues

When splitting a large piece of work into focused issues, keep the umbrella open as a tracker that links each child issue with a checkbox; close it once every child is closed or explicitly deferred.

**Single-repo boundary (non-negotiable).** An umbrella issue may only track child issues **in this same repository**. Do **not** open a tracker here that coordinates, checklists, or drives work in sibling repos (`azure-functions-validation-python`, `azure-functions-logging-python`, etc.), and do **not** ask another repo to host a tracker for this one. Each repository in the DX Toolkit is operated **independently** — it owns its own backlog, fix, verification, and release cadence.

- A bug that also exists in sibling repos is **not** one shared work item — it is N independent per-repo issues. File (or ask the maintainer to file) a separate issue in each affected repo; fix and release each on its own timeline.
- Cross-repo audit findings may be **referenced** from a local issue for context (a plain link is fine), but the local issue must be closeable on this repo's work alone. Never leave an issue here open pending another repo's fix.
- If you catch yourself building a checklist of `owner/other-repo#N` items to "drive from here," stop — that is the cross-repo umbrella anti-pattern. Close it as `not planned` and let each repo track its own child issue.

### Issue-creation access (fleet policy)

Keep issue creation **open/unrestricted** on every public toolkit repository (issue tracker enabled, no `interaction-limits`). External bug reports are the only inbound support channel, so restricting issue creation suppresses the signal we most need. Do not enable an interaction limit or restrict issue creation without an explicit, documented reason recorded in an issue first.

### Project management model

This repository is **issue-based, not milestone-based**. Track and group work using issues plus the existing label taxonomy — do **not** introduce parallel structures.

- Plan and group multi-issue efforts with an **umbrella tracker issue** (see above) plus the existing `priority:*` labels. Do **not** create GitHub Milestones — none exist by design, and their absence is an intentional signal, not an oversight.
- Do **not** invent new label taxonomies (e.g. `epic:*`, `vNext`, release-tag labels) to group work. Reuse `priority:*`, `area:*` (only where they already exist), and the umbrella issue. Propose any new label in discussion and wait for explicit approval before creating it.
- Treat optional or tentative suggestions ("we could…", "it might be nice to…", "~해도 괜찮아") as **discussion, not a directive**. Confirm intent before making any structural change to how work is tracked (milestones, labels, project boards, issue hierarchies).
- Before adding any organizational structure, check whether the repository already has an established convention. A category being empty or unused (zero milestones, no `epic:*` labels) is evidence to follow the existing pattern, not to introduce a new one.

## Validation
- `make test`
- `make lint`
- `make typecheck`
- `make build`

## Release Process

Three tools, one job each. Nothing else participates.

| Tool | Owns |
|---|---|
| **Release Please** | version decision, `__version__`, `CHANGELOG.md`, Release PR, tag, GitHub Release |
| **GitHub Actions** | verification, real-Azure e2e, PyPI publish |
| **Hatch** | building the Python package (reads `__version__` via `[tool.hatch.version]`) |

- **Do NOT manually edit version strings, `CHANGELOG.md`, `.release-please-manifest.json`, or tags.** Release Please owns all of them. The public-API test reads `__version__` against `importlib.metadata.version(...)`, so no test changes are needed when bumping.
- Releases are driven by **Conventional Commits** on `main`, but only **user-facing** types cut one: `fix:` → patch, `perf:`/`revert:` → patch, `feat:` → minor, `feat!:`/`fix!:`/`BREAKING CHANGE:` → breaking. While this package is pre-1.0, `bump-minor-pre-major` keeps a breaking change on the `0.x` line (`0.25.1` → `0.26.0`, never `1.0.0`).
- **`docs:`, `ci:`, `chore:`, `test:`, `build:`, `style:` and `refactor:` do not cut a release.** They are marked `"hidden": true` in `release-please-config.json`, which keeps them out of `CHANGELOG.md`; when a batch of commits contains nothing else, the release notes render empty and Release Please logs `No user facing commits found since <sha> - skipping` and opens no Release PR. Merging such a PR and seeing no version change is the intended outcome, not a broken pipeline. A breaking change still releases whatever its type is.
- There are **no release Makefile targets**. `make release-*`, `make changelog`, `make tag-release`, and `make publish-pypi` were deleted; a local `hatch publish` would have skipped every gate below.

### Flow

```
feat:/fix: PR merged into main
        |
  Release Please  ->  Release PR (version + CHANGELOG)
        |  maintainer reviews and merges
  tag vX.Y.Z + GitHub Release
        |
  publish-pypi.yml  (started by the tag)
        build -> lib-tests -> cookbook-smoke -> cookbook-host-smoke
              -> azure-e2e -> PyPI
```

1. Merge Conventional-Commit PRs into `main`. Release Please keeps an open **Release PR** showing exactly what the next release would be.
2. Merging that Release PR is the act of cutting a release.
3. Release Please tags the release commit and publishes the GitHub Release. The tag starts `publish-pypi.yml`.
4. Every verification tier runs in that one workflow. PyPI upload happens only if all of them pass.
5. Nothing else to update: `docs/changelog.md` embeds the root `CHANGELOG.md`, so the docs site picks up the new entry automatically.

**Certification is an in-chain gate.** `azure-e2e` deploys to real Azure and runs the live e2e suite at the same ref being published, so it covers the exact published commit by construction. There is no separate certification step to dispatch, and no cross-run SHA or freshness matching to get wrong.

**`RELEASE_PLEASE_TOKEN` is load-bearing.** It is a fine-grained PAT (repository: this repo only; permissions: Contents read/write, Pull requests read/write) stored as a repository secret. The default `GITHUB_TOKEN` cannot trigger other workflows, which would leave the Release PR without the required status checks — permanently unmergeable — and would stop the tag from starting `publish-pypi.yml`. The PAT grants repository write only; PyPI upload uses OIDC Trusted Publishing and cannot be reached with it. **Fine-grained PATs expire** (at most one year): when it does, the workflow fails at the release-please step and no Release PR appears. Regenerate it and update the secret before the expiry date.

### Tiered runtime verification (what gates a release)

Every tier runs inside `publish-pypi.yml` on the tag, and **all of them gate the upload**:

| Tier | Catches |
| --- | --- |
| `build` | tag/`__version__` mismatch; produces the one artifact that is later uploaded |
| `lib-tests` | library unit regressions |
| `cookbook-smoke` | downstream import/registration drift |
| `cookbook-host-smoke` | candidate wheel installs cleanly and a real `func` host + Azurite boots with it present, no cloud. NOTE: the cookbook HTTP examples do not import this package, so this is a host-boot smoke, **not** proof of this package's own runtime behavior (tracked separately) |
| `azure-e2e` | cloud-only drift — deploys to real Azure, runs the live e2e suite, uploads an `azure-cert` record |
| `publish` | uploads the exact artifact `build` produced; it never rebuilds |

### Recovery
- **Any gate failed.** Nothing was uploaded, so the version is still free. Fix the cause and re-run the workflow on the same tag (`gh workflow run publish-pypi.yml --ref main -f tag=vX.Y.Z`), or fix forward on `main` and let the next Release PR cut a new version. Never move or reuse a tag.
- **A tag exists but was never published.** A valid resting state. Re-run publish, or abandon the version and let the next release take the following number.
- **Release PR stopped appearing.** Check for a stale `autorelease: pending` label on an already-merged Release PR — Release Please treats that as a release still in flight and will not open another. This failure is silent: the workflow still reports success.
- **Break-glass (automation unavailable).** Bump `__version__`, match `.release-please-manifest.json`, commit, tag, and push. The tag starts the same gated workflow — never bypass it.


### Post-release verification

**Verify the release against the dogfood cookbook.** Once **Publish to PyPI** succeeds, confirm the downstream consumer still passes on the freshly published version:

- In [`azure-functions-cookbook-python`](https://github.com/yeongseon/azure-functions-cookbook-python), upgrade to the new release (`hatch run pip install -U "azure-functions-openapi>=X.Y,<1"`) and run `make test`.
- Treat any new `RuntimeWarning`/`DeprecationWarning` surfaced by this library during the cookbook run as a release-blocking signal — decorator-order and API-drift problems are reported as warnings, so a clean run (zero warnings from this package) is part of the release gate.
- If the cookbook pins a lower bound (`azure-functions-openapi>=X.Y,<1`), bump it to the new minor in the same verification PR so examples are tested against the version they advertise.
- A release is **not** considered done until the cookbook passes on the published version.

   - In [`azure-functions-cookbook-python`](https://github.com/yeongseon/azure-functions-cookbook-python), upgrade to the new release (`hatch run pip install -U "azure-functions-openapi>=X.Y,<1"`) and run `make test`.
   - Treat any new `RuntimeWarning`/`DeprecationWarning` surfaced by this library during the cookbook run as a release-blocking signal — decorator-order and API-drift problems are reported as warnings, so a clean run (zero warnings from this package) is part of the release gate.
   - If the cookbook pins a lower bound (`azure-functions-openapi>=X.Y,<1`), bump it to the new minor in the same verification PR so examples are tested against the version they advertise.
   - A release is **not** considered done until the cookbook passes on the published version.

## Golden Commands

Use Makefile entry points only. Do not bypass the Makefile in CI or contributor guidance.

| Purpose | Command |
| --- | --- |
| Environment setup | `make install` |
| Format code | `make format` |
| Check formatting (`src`, `tests`) | `make format-check` |
| Lint | `make lint` |
| Type check | `make typecheck` |
| Tests | `make test` |
| Coverage | `make cov` |
| Full validation | `make check-all` |
| Docs build | `make docs` |
| Package build | `make build` |

## Compatibility Rules

- Runtime code must remain compatible with Python `3.11`.
- Public APIs must be fully typed.
- Avoid silent behavior changes.
- Breaking changes require explicit documentation and versioning discussion.

## Testing Rules

- Public APIs require tests.
- Bug fixes require regression tests.
- Representative and complex examples must remain smoke-tested.
- `make check-all` is the minimum merge gate.

## Commit Rules

Titles for issues, pull requests, and commits follow the **Title Convention** in [`CONTRIBUTING.md`](CONTRIBUTING.md#title-convention), the single source of truth for the format and the allowed types.

## Agent Rules

When using AI-assisted development:

- Prefer small, reviewable changes.
- Do not guess about behavior that can be verified.
- Keep repository structure aligned with sibling repositories.
- Update docs, examples, and tests together when behavior changes.

## Final Rule

If it is not automated, it will drift.
If it is not documented, it is not a stable rule.

## Branch Hygiene

- Merged PR branches are deleted automatically ("Automatically delete head branches" is enabled on this repository); keep that setting on.
- When merging from the CLI, always pass `--delete-branch` (e.g. `gh pr merge --squash --delete-branch`) so the head branch is removed.
- Never delete `main` or `gh-pages`, and never delete a branch that still has an open PR.
- Run `git fetch -p` periodically to prune stale local tracking refs.
