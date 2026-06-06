# AGENTS.md

## Purpose
`azure-functions-openapi` provides OpenAPI generation and validation support for Python Azure Functions.

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

## PR Workflow

**Always issue-first.** Before opening any PR:

1. Run `gh issue list` to check whether a tracking issue already exists for the change.
2. If no issue exists, create one following the Issue Conventions below before writing any code.
3. Open the PR only after the issue exists. The PR body **must** include `Closes #N` for every
   issue it resolves — never open a PR that cannot be traced back to an issue.

**Non-negotiable:** a PR without a linked issue will be rejected at review.

## Issue Conventions

Follow these conventions when opening issues so the backlog stays consistent with sibling DX Toolkit repositories.

### Title

- Use Conventional Commit prefixes: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `ci:`, `build:`, `perf:`.
- Add a scope qualifier when it narrows the area: `feat(cli):`, `docs(spec):`, `refactor(bridge):`.
- Keep the title imperative, under ~80 characters, no trailing period.
- Do **not** put `[P0]` / `[P1]` / `[P2]` (or any priority marker) in the title — priority lives in the body.

### Body

Use the following sections, in order, omitting any that do not apply:

```
## Priority: P0 | P1 | P2 (target vX.Y.Z, optional)

## Context
What problem this issue addresses and why now.

## Acceptance Checklist
- [ ] Concrete, verifiable items.

## Out of scope
- Items intentionally excluded, with links to the issues that track them.

## References
- PRs, ADRs, sibling issues, external docs.
```

### Labels

- Apply at least one of `bug`, `enhancement`, `documentation`, `chore`.
- Add `area:*` labels when they exist in the repository.
- Use `blocker` only when the issue blocks a release.

### Umbrella issues

When splitting a large piece of work into focused issues, keep the umbrella open as a tracker that links each child issue with a checkbox; close it once every child is closed or explicitly deferred.

## Validation
- `make test`
- `make lint`
- `make typecheck`
- `make build`

## Release Process
- Version is managed via `hatch` (dynamic from `src/azure_functions_openapi/__init__.py`).
- **Do NOT manually edit version strings.** Use the Makefile targets below. The public-API test reads `__version__` against `importlib.metadata.version(...)`, so no test changes are needed when bumping.

### Commands
- `make release-patch` — bump patch version, update changelog, tag, and push
- `make release-minor` — bump minor version, update changelog, tag, and push
- `make release-major` — bump major version, update changelog, tag, and push
- `make release VERSION=x.y.z` — set explicit version, update changelog, tag, and push
- `make tag-release VERSION=x.y.z` — create and push an annotated tag (used internally by release targets)

### Flow
1. `make release-patch` (or `-minor` / `-major`) on `main`
2. This runs: `hatch version` → `git commit` → `make changelog` → `git commit` → `git tag` → `git push`
3. Tag push triggers **Publish to PyPI** GitHub Actions workflow automatically.
4. Update `docs/changelog.md` separately if needed (different format from `CHANGELOG.md`).
