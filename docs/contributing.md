# Contributing Guide

We welcome contributions to the `azure-functions-openapi` project.

## Getting Started

1. Fork the repository on GitHub.
2. Clone your fork locally:

```bash
git clone https://github.com/<your-username>/azure-functions-openapi-python.git
cd azure-functions-openapi-python
```

3. Set up the development environment:

```bash
make install
```

This creates a Hatch-managed virtual environment and installs pre-commit hooks.

## Branch Strategy

This project uses **GitHub Flow**. Branch from `main` and merge back to `main`.

Recommended branch prefixes:

| Prefix | Purpose |
| --- | --- |
| `feat/` | New features |
| `fix/` | Bug fixes |
| `docs/` | Documentation-only changes |
| `chore/` | Tooling and maintenance |
| `ci/` | Workflow updates |
| `refactor/` | Code restructuring without behavior change |

Example:

```bash
git checkout main
git pull origin main
git checkout -b feat/add-cookie-parameter-support
```

## Development Workflow

1. **Create a feature branch** from `main`.
2. **Implement changes** in `src/azure_functions_openapi/` and add corresponding tests in `tests/`.
3. **Run the local quality gate**:

```bash
make check-all
```

This runs linting (Ruff), type checking (mypy), and the full test suite.

4. **Commit changes** using [Conventional Commits](https://www.conventionalcommits.org/) format:

```bash
git commit -m "feat: add cookie parameter support to @openapi decorator"
```

5. **Push and open a Pull Request** to `main`.

## Commit Message Format

Titles for issues, pull requests, and commits follow the **Title Convention** in [`CONTRIBUTING.md`](https://github.com/yeongseon/azure-functions-openapi-python/blob/main/CONTRIBUTING.md#title-convention), the single source of truth for the format and the allowed types.

## Pull Request Guidelines

### Before submitting

- Run `make check-all` and verify it passes.
- Ensure new code has test coverage. The suite is gated at 95% (`fail_under = 95` in `pyproject.toml`).
- Update documentation if the change affects public API or behavior.
- Keep the PR focused on a single concern.

### PR description

Describe what changed and why. Reference related issues with `Fixes #N` or `Closes #N`.

### Review process

- Branch protection does not require a review approval; the required CI checks are the merge gate. Maintainers still review anything beyond a trivial change.
- CI must pass on all Python versions (3.11 -- 3.14).
- Merge with "Squash and merge" to keep the commit history clean.

## Code Style

### Formatting

- **Ruff** does everything: formatting, linting, and import sorting. There is no Black in this project.
- `ruff format` and `ruff check` both run as pre-commit hooks.

### Type annotations

- All public functions must have complete type annotations.
- Use Python 3.11+ syntax.
- `mypy` strict mode is enforced in CI.

### Naming conventions

| Element | Convention | Example |
| --- | --- | --- |
| Functions | `snake_case` | `generate_openapi_spec` |
| Classes | `PascalCase` | `BaseModel` |
| Constants | `UPPER_SNAKE_CASE` | `OPENAPI_VERSION_3_0` |
| Private | `_leading_underscore` | `_validate_route` |

## Quality Gates

### Makefile targets

| Target | Description |
| --- | --- |
| `make format` | Format code with `ruff format` |
| `make format-check` | Check formatting without writing |
| `make style` | `ruff check` + `ruff format --check` |
| `make lint` | Run Ruff + mypy |
| `make typecheck` | Run mypy type checking |
| `make security` | Run Bandit security scan |
| `make test` | Run pytest |
| `make cov` | Run tests with coverage (gated at 95%) |
| `make lint-workflows` | Lint release workflows, action pins, Hatch matrix |
| `make check` | Run lint + typecheck |
| `make check-all` | Run lint-workflows + check + test + security (full gate) |
| `make docs` | Build the MkDocs site |

See [Development Guide](development.md#makefile-targets) for the complete list.

### Pre-commit hooks

| Tool | Purpose |
| --- | --- |
| Ruff | Formatter, linter, and import sorter |
| mypy | Static type checker |
| Bandit | Security scanner (`src/` only) |

Pinned versions live in `.pre-commit-config.yaml` (hook `rev`) and
`pyproject.toml` (the `dev` dependency pins), so they are not duplicated here.

Run all hooks manually:

```bash
make precommit
```

## Example Coverage Policy

Examples in `examples/` are part of the supported API experience. They must remain
functional and have smoke test coverage.

- Keep one representative example for the minimal OpenAPI workflow (`webhook_receiver`).
- Keep one complex example for multi-endpoint behavior (`report_jobs`).
- Keep one integration example (`notification_request`).
- Add or update smoke tests whenever an example changes.

## Reporting Issues

Open an issue on GitHub with:

1. A clear description of the problem or feature request.
2. Steps to reproduce (for bugs).
3. Expected vs. actual behavior.
4. Python version, azure-functions version, and OS.

## Code of Conduct

Be respectful and inclusive. See the [Code of Conduct](https://github.com/yeongseon/azure-functions-openapi-python/blob/main/CODE_OF_CONDUCT.md) for details.
