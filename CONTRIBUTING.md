# Contributing Guide

We welcome contributions to the `azure-functions-openapi` project.

## Branch Strategy

Use GitHub Flow and branch from `main`.

Recommended branch prefixes:

- `feat/` for new features
- `fix/` for bug fixes
- `docs/` for documentation-only changes
- `chore/` for tooling and maintenance
- `ci/` for workflow updates

## Development Workflow

1. Create a branch from `main`.
   ```bash
   git checkout main
   git pull origin main
   git checkout -b feat/your-feature-name
   ```
2. Write code and tests.
3. Run the local quality gate.
   ```bash
   make check-all
   ```
4. Push and create a pull request.
   ```bash
   git push origin feat/your-feature-name
   ```

## Local development quickstart

The package supports Python `>=3.11,<3.15` (currently Python 3.11 through 3.14).
The default Hatch development environment is intentionally provisioned with
Python 3.11, so `make install` may download or select Python 3.11 even when
your machine's default interpreter is newer. From the repository root, run:

```bash
make install
```

This creates the repository's `.venv` when needed, installs Hatch, creates the
Hatch environment, and installs the development dependencies. No Azure account
or deployed Function App is required for the standard local checks.

Run the same checks used by the project locally:

```bash
make test
make lint
make typecheck
make build
```

The default test command excludes real-Azure end-to-end tests. Those tests need
an `E2E_BASE_URL`; use `make e2e-azure` only when that environment is available.

## Project Commands

```bash
make format      # Format code with ruff
make lint        # Lint with ruff
make typecheck   # Type check with mypy
make test        # Run tests
make cov         # Run tests with coverage
make perf        # Check spec-generation performance budgets
make check-all   # Run the full local gate
```

Before opening a PR, run `ruff format --check <changed-python-files>` (or
`ruff format <changed-python-files>` to fix them). `make format-check` checks
`src` and `tests` without changing files. CI checks those same trees and also
reports formatting failures on changed Python files in a dedicated step.

## GitHub Actions Pinning

All external `uses:` references in `.github/workflows/` MUST pin to a
full 40-character commit SHA with a trailing comment documenting the
released version or channel. Example:

```yaml
- uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6
```

This applies to first-party (`actions/*`, `github/*`, `azure/*`) and
third-party Actions alike.

**Rationale.** Mutable tags (including immutable-looking version tags
like `@v6.0.1`) can be retroactively moved by an attacker who gains
write access to the upstream repository. The
[`tj-actions/changed-files` compromise (CVE-2025-30066, March 2025)](https://github.com/advisories/GHSA-mrrh-fwg8-r2c3)
demonstrated this exact failure mode: ~23,000 repositories had their CI
secrets exfiltrated, and only workflows that pinned to a commit SHA were
safe. GitHub's own guidance now identifies SHA pinning as
[the only way to use an Action as an immutable release](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions#using-third-party-actions),
and OpenSSF Scorecard's
[`Pinned-Dependencies` check](https://github.com/ossf/scorecard/blob/main/docs/checks.md#pinned-dependencies)
flags anything weaker as Medium-risk.

Dependabot updates SHA-pinned references on the configured schedule and
keeps the trailing version comment in sync, so the human-readable
context never drifts from the pinned commit.

**Approved exceptions.** The following mutable refs are the only ones
permitted in this repository and are flagged with an inline comment at
the call site:

- `pypa/gh-action-pypi-publish@release/v1` — PyPA-maintained stable
  release channel; this pinning style is explicitly recommended upstream.
- Local composite actions (`uses: ./...`) — versioned with the repo.

When adding a new external Action, resolve the SHA with
`git ls-remote <repo-url> 'refs/tags/<tag>^{}'`. The trailing `^{}`
**dereferences** the ref to its target commit; without it, an
*annotated* tag returns the tag-object SHA instead of the commit SHA,
and the tag-object SHA is **not** a valid `uses:` target.

```bash
# Annotated tag — the two forms return *different* SHAs:
git ls-remote https://github.com/Azure/login 'refs/tags/v3.0.0' 'refs/tags/v3.0.0^{}'
# 93381592...   refs/tags/v3.0.0       <- tag object, do NOT pin to this
# 532459ea...   refs/tags/v3.0.0^{}    <- commit, pin to this one

# Lightweight tag — only the non-deref form returns a row, and it is
# already the commit SHA. Always include the `^{}` form anyway so the
# same command works for both tag types:
git ls-remote https://github.com/actions/setup-python 'refs/tags/v6' 'refs/tags/v6^{}'
```

Single-quote the `refs/...^{}` argument so the `{}` and `^` are not
interpreted by your shell (notably zsh with `EXTENDED_GLOB`).

## Example Coverage Policy

Examples are part of the supported API experience and should stay verified.

- Keep one representative example for the minimal OpenAPI workflow.
- Keep one complex example for multi-endpoint and schema-heavy behavior.
- Add or update smoke tests whenever an example changes.
- Prefer lightweight smoke coverage over infrastructure-heavy end-to-end tests.

## Documentation Propagation Checklist

Documentation is multi-surfaced (English README, translated READMEs, `docs/`,
and generated changelog). When you change a user-facing fact, propagate it
across every surface so the docs do not drift:

- [ ] Update `README.md`. It is the canonical source of truth.
- [ ] Optionally mirror the change into the translations (`README.ko.md`,
      `README.ja.md`, `README.zh-CN.md`). Translations are best-effort and
      community-maintained: updating them is **not** required in the same pull
      request, and translation drift never blocks a merge. Each translated
      README carries a staleness banner pointing back to the English source.
- [ ] Update the matching page under `docs/` (e.g. `docs/cli.md` when CLI
      defaults or flags change).
- [ ] Keep changelog single-sourced: edit the root `CHANGELOG.md` only.
      `docs/changelog.md` includes it via the `--8<-- "CHANGELOG.md"` snippet,
      so never hand-edit `docs/changelog.md`.
- [ ] Run `make docs` (mkdocs build) and confirm it completes without warnings.


## Title Convention

This section is the single source of truth for issue, pull request, and commit titles in this repository. `AGENTS.md`, the pull request template, the issue forms, and the documentation site point here instead of restating the rules.

Issues, pull requests, and the final squash commit on the default branch all use:

```text
type: description
type(scope): description
```

- Write titles in English.
- `type` and `scope` are lowercase. Put exactly one space after the colon.
- `scope` is optional. Add it only when it narrows the area; do not add one just for uniformity.
- `description` states what changes and why, concisely. Start with a lowercase word, but keep the spelling of API names, acronyms, error codes, and proper nouns.
- No trailing period.
- No priority, size, status, or owner markers, and no bracket prefixes such as `[Bug]`, `[Feature]`, or `[WIP]`. Use labels and Draft pull requests instead.
- An issue title may describe the problem; the pull request title describes the change that resolves it. Keep them aligned when they cover the same work, without forcing identical wording when the scope differs.
- Do not put issue numbers in pull request titles. Link issues in the pull request body with `Closes #123` or `Refs #123`.

| type | use for |
|---|---|
| `feat` | a user-facing feature or capability |
| `fix` | a bug fix in product behavior |
| `docs` | documentation only |
| `test` | adding or changing tests |
| `perf` | a performance improvement |
| `refactor` | internal restructuring that keeps external behavior |
| `ci` | CI and automation workflows |
| `build` | build, packaging, and dependency changes |
| `chore` | maintenance that fits none of the above |
| `style` | formatting only, no behavior change |
| `revert` | reverting an earlier change |

A breaking change adds `!` before the colon: `type!: description` or `type(scope)!: description`. Whether a change is breaking, and how it is released, is decided by the Release Process in [AGENTS.md](AGENTS.md), not by the title alone. Release Please reads these titles from the squash commits on `main`: `feat`, `fix`, `perf` and `revert` are treated as user-facing, so they appear in `CHANGELOG.md` and drive the version bump. The remaining types are marked hidden — they neither appear in the changelog nor cut a release, unless the commit carries a breaking change.

Examples:

```text
fix: decode nonempty NULL-only collection results
feat(cli): add a JSON output option
docs(readme): clarify the local setup steps
refactor!: rename the public configuration keys
```

Not accepted: `[Bug] crash on save` (bracket prefix, no type), `Fix: crash on save` (uppercase type), `feature: add export` (type not in the table), `fix: crash on save.` (trailing period), `fix: decode results (#503)` (the pull request number belongs in the body).

Pull requests are squash-merged and the pull request title becomes the final commit title. GitHub appends the pull request number by itself, so `fix: decode nonempty NULL-only collection results` lands on `main` as `fix: decode nonempty NULL-only collection results (#503)`. Do not write that number into the title yourself — the check rejects a title ending in `(#123)`, because it would be doubled. Link the issue from the pull request body instead, for example `Closes #503`. The **PR title** check validates the format whenever a pull request is opened, edited, reopened, or updated. Individual commits on a branch are not checked.

Issue titles are not enforced. Anyone can open an issue without knowing this convention; maintainers adjust the title during triage.

## Releases

Merging to `main` does not publish a release.

Release Please keeps an open **Release PR** showing what the next version would
be; merging that PR is what cuts the release, and it is what creates the `v*`
tag that starts the publish workflow. Publishing happens only after the release
verification requirements have been satisfied. Contributors never need to bump a
version or tag anything in an ordinary pull request.

See `AGENTS.md` for the maintainer-only release procedure.

## Code of Conduct

Be respectful and inclusive. See our [Code of Conduct](CODE_OF_CONDUCT.md) for details.
