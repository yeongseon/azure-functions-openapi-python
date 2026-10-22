# Development Guide

This guide covers how to set up a local development environment, run tests, and manage code quality for **azure-functions-openapi**, using Hatch and a Makefile for workflow automation.

---

## Prerequisites

- **Python 3.11+** installed on your system
- **Git** for version control
- **Hatch** as the build and environment manager (installed via `pip install hatch`)
- **Make** for running the provided Makefile targets

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
├── release-please-config.json      # Release Please configuration
├── .release-please-manifest.json   # Release Please version manifest
├── .pre-commit-config.yaml
├── Makefile
├── pyproject.toml
└── README.md
```

- **`Makefile`** — common commands for environment setup, testing, linting, and building. Release and publish targets are retired; see [Release Process](release_process.md).
- **`pyproject.toml`** — Hatch environments, project metadata, and tool configuration.
- **`release-please-config.json`** / **`.release-please-manifest.json`** — Release Please configuration and the tracked version; these drive version bumps, `CHANGELOG.md`, and release tags.
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

There is no Black in this project. Ruff handles both formatting and linting.

| Tool   | Purpose                            |
|--------|------------------------------------|
| ruff   | Formatter + linter + import sorter |
| mypy   | Static type checker                |
| bandit | Security checker on `src/` only    |

Pinned versions live in two places and are the source of truth, so this table
deliberately does not repeat them:

- `.pre-commit-config.yaml` — the `rev` of each hook
- `pyproject.toml` — the `dev` optional-dependency pins used by `make` targets

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
| `make shell` | Open a shell inside the Hatch env |
| `make format` | Format code (ruff format) |
| `make format-check` | Check formatting without writing (ruff format --check) |
| `make style` | Run `ruff check` + `ruff format --check` |
| `make lint` | Run linter (ruff + mypy) |
| `make typecheck` | Run mypy type checking |
| `make security` | Run Bandit security scan |
| `make test` | Offline pytest with 95% coverage, saved JUnit/coverage/summary |
| `make cov` | Run tests with coverage (gate: `fail_under = 95`) |
| `make e2e-local` | Run e2e tests against local Azurite on `:7071` |
| `make e2e-azure` | Run e2e tests against Azure (`E2E_BASE_URL` required) |
| `make lint-workflows` | Lint release workflows, action pins, and the Hatch matrix |
| `make install-ci` | Install extras on CI's explicitly selected interpreter |
| `make check` | Non-mutating lint, format, types once, Bandit and policy checks |
| `make integration` | Real Functions host + isolated Azurite, managed readiness/cleanup |
| `make verify` | Check + test + integration + perf + wheel smoke + strict docs |
| `make check-all` | Exact backward-compatible alias for `verify` |
| `make report` | Render last saved evidence without rerunning tests |
| `make docs` | Build the MkDocs site |
| `make docs-serve` | Serve the docs locally with live reload |
| `make demo` | Run the Swagger UI and example demos |
| `make build` | Build package |
| `make version` | Show the current version |
| `make publish-test` | Publish to TestPyPI |
| `make precommit` | Run all pre-commit hooks |
| `make precommit-install` | Install pre-commit hooks |
| `make doctor` | Show environment diagnostic info |
| `make reset` | Deep clean, then reinstall the env |
| `make hatch-clean` | Remove the Hatch environment |
| `make clean` | Remove build artifacts |
| `make clean-all` | Alias of artifact-only `clean`; never deletes `.venv` |
| `make help` | List available targets |

Coverage is enforced at **95%** (`fail_under = 95` in `pyproject.toml`); a drop
below that fails the build.

`make doctor` is read-only and fails for missing required tools. It reports the
actual interpreter; func/Azurite are required only for integration/verify.
Local commands use Hatch's Python 3.11; CI uses its selected `PYTHON` directly.
Install Hatch once in an isolated tool environment; routine commands never upgrade
pip or reinstall Hatch. `install` does not change the global interpreter.

All targets besides the canonical contract (`install`, `install-ci`, `doctor`,
`format`, `format-check`, `check`, `test`, `integration`, `verify`, `e2e-azure`,
`report`, `clean`) are focused/partial or maintenance commands. Demos are optional.
`e2e-local` is a local-emulator check, never real Azure certification.

Evidence is saved under gitignored `test-results/`: `test/` contains `junit.xml`,
`coverage.xml`, `summary.json`; `integration/` contains `junit/junit.xml`, logs and
summary; `verify/` contains aggregate summary, `lanes.json` and environment metadata;
`azure-e2e/` contains JUnit, logs and summary with the expected deployed version.
Each lane also saves `environment.json`. Console and Actions summaries use the same
JSON counts/status. PASS requires execution; zero/all-skipped/missing prerequisites
are INCOMPLETE, errors are FAIL, and NOT_APPLICABLE is reserved for unsupported lanes.
`verify` never silently omits a required lane. `e2e-azure` requires both
`E2E_BASE_URL` and `E2E_EXPECTED_VERSION` and never provisions resources.

> For the full release workflow, see [Release Process](release_process.md).

---

## Tips

- Ensure you're using Python 3.11+.
- Use `make check-all` before committing to validate your changes.
- Prefer `make` commands to ensure consistent dev experience across platforms.
- Follow [Conventional Commits](https://www.conventionalcommits.org/) for proper changelog generation.
