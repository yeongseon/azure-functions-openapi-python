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

All commits must follow the Conventional Commits specification. The changelog is
generated automatically from commit messages using git-cliff.

### Structure

```text
<type>(<optional scope>): <description>

[optional body]

[optional footer(s)]
```

### Allowed types

| Type | Description |
| --- | --- |
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or updating tests |
| `chore` | Maintenance, dependency updates, tooling |
| `ci` | CI/CD workflow changes |
| `perf` | Performance improvement |

### Examples

```bash
git commit -m "feat: add OpenAPI 3.1 nullable type conversion"
git commit -m "fix: handle empty request body in POST operations"
git commit -m "docs: add security scheme examples to usage guide"
git commit -m "refactor: extract schema builder into utils module"
git commit -m "chore: update ruff to v0.15.0"
```

## Pull Request Guidelines

### Before submitting

- Run `make check-all` and verify it passes.
- Ensure new code has test coverage (target: 85%+).
- Update documentation if the change affects public API or behavior.
- Keep the PR focused on a single concern.

### PR description

Describe what changed and why. Reference related issues with `Fixes #N` or `Closes #N`.

### Review process

- At least one approval is required before merging.
- CI must pass on all Python versions (3.10 -- 3.14).
- Merge with "Squash and merge" to keep the commit history clean.

## Code Style

### Formatting

- **Black** for code formatting (line length: default).
- **Ruff** for linting and import sorting.
- Both run as pre-commit hooks.

### Type annotations

- All public functions must have complete type annotations.
- Use Python 3.10+ syntax (PEP 604 `X | Y`, PEP 585 `list[T]`).
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
| `make format` | Format code with Ruff and Black |
| `make lint` | Run Ruff linter |
| `make typecheck` | Run mypy type checking |
| `make security` | Run Bandit security scan |
| `make test` | Run pytest |
| `make cov` | Run tests with coverage |
| `make check-all` | Run lint + typecheck + test (full gate) |

### Pre-commit hooks

| Tool | Version | Purpose |
| --- | --- | --- |
| Black | 26.1.0 | Code formatter |
| Ruff | v0.14.13 | Linter and import sorter |
| mypy | v1.19.1 | Static type checker |
| Bandit | 1.9.3 | Security scanner (src/ only) |

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
