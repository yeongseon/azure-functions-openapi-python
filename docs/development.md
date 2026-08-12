# Development Guide

This guide covers how to set up a local development environment, run tests, and manage code quality for **azure-functions-openapi**, using Hatch and a Makefile for workflow automation.

---

## Prerequisites

- **Python 3.10+** installed on your system
- **Git** for version control
- **Hatch** as the build and environment manager (installed via `pip install hatch`)
- **Make** for running the provided Makefile targets
- **git-cliff** for changelog generation (install from [git-cliff.org](https://git-cliff.org/))

---

## Project Structure

```text
azure-functions-openapi/
├── src/
│   └── azure_functions_openapi/
│       ├── __init__.py
│       ├── cli.py
│       ├── decorator.py
│       ├── openapi.py
│       └── swagger_ui.py
├── tests/
├── examples/
├── docs/
├── .github/
│   └── workflows/
├── cliff.toml                # git-cliff changelog configuration
├── .pre-commit-config.yaml
├── Makefile
├── pyproject.toml
└── README.md
```

- **`Makefile`** — common commands for environment setup, testing, linting, releasing, and publishing.
- **`pyproject.toml`** — Hatch environments, project metadata, and tool configuration.
- **`cliff.toml`** — git-cliff configuration for changelog generation from conventional commits.
- **`src/azure_functions_openapi/`** — core library code including decorator, OpenAPI generator, and Swagger UI.
- **`tests/`** — unit and integration tests.
- **`docs/`** — documentation files served by MkDocs.
- **`examples/`** — sample Azure Functions projects demonstrating library usage.

---

## Initial Setup

1. **Clone the repository**:
    ```bash
    git clone https://github.com/yeongseon/azure-functions-openapi-python.git
    cd azure-functions-openapi-python
    ```

2. **Create environment and install dependencies**:
    ```bash
    make install
    ```

3. **Install pre-commit hooks**:
    ```bash
    make precommit-install
    ```

---

## Pre-commit Hooks

This project uses pre-commit to ensure consistent code quality across formatting, linting, typing, and security.

| Tool   | Version  | Purpose                        |
|--------|----------|--------------------------------|
| ruff   | v0.15.5  | Formatter + linter + import sorter |
| mypy   | v1.19.1  | Static type checker            |
| bandit | 1.9.4    | Security checker on `src/` only |

### Bandit Configuration

- Only scans `src/` directory
- Skips `tests/`
- Uses `pass_filenames: false` for full-directory analysis

### Run Hooks Manually

```bash
make precommit
```

---

## Development Workflow

1. **Create a feature branch**:
    ```bash
    git checkout -b feature/your-description
    ```

2. **Implement changes** in `src/azure_functions_openapi/` and add corresponding tests in `tests/`.

3. **Run quality checks** locally:
    ```bash
    make check-all
    ```

4. **Commit changes** with [Conventional Commits](https://www.conventionalcommits.org/) format:
    ```bash
    git commit -m "feat: add new parameter type support"
    ```

5. **Push and open a Pull Request** to `main`.

---

## Makefile Targets

Use these as the **golden commands** for local validation and CI parity. Prefer `make` targets over direct tool commands.

| Target | Description |
|--------|-------------|
| `make install` | Create Hatch env and install pre-commit hooks |
| `make format` | Format code (ruff) |
| `make lint` | Run linter (ruff + mypy) |
| `make typecheck` | Run mypy type checking |
| `make security` | Run Bandit security scan |
| `make test` | Run pytest |
| `make cov` | Run tests with coverage |
| `make check` | Run lint + typecheck |
| `make check-all` | Run lint + typecheck + test |
| `make build` | Build package |
| `make changelog` | Regenerate CHANGELOG.md via git-cliff |
| `make release-patch` | Bump patch version + changelog + tag |
| `make release-minor` | Bump minor version + changelog + tag |
| `make release-major` | Bump major version + changelog + tag |
| `make publish-pypi` | Publish to PyPI |
| `make publish-test` | Publish to TestPyPI |
| `make precommit` | Run all pre-commit hooks |
| `make precommit-install` | Install pre-commit hooks |
| `make doctor` | Show environment diagnostic info |
| `make clean` | Remove build artifacts |
| `make clean-all` | Deep clean (caches, coverage, venv) |

> For the full release workflow, see [Release Process](release_process.md).

---

## Tips

- Ensure you're using Python 3.10+.
- Use `make check-all` before committing to validate your changes.
- Prefer `make` commands to ensure consistent dev experience across platforms.
- Follow [Conventional Commits](https://www.conventionalcommits.org/) for proper changelog generation.
