# Agent Playbook

## Source Of Truth
- `AGENTS.md` for repository-wide engineering and agent rules.
- `README.md` for installation, quick start, and CLI examples.
- `CONTRIBUTING.md` for branch, commit, and release workflow.
- `pyproject.toml` and `Makefile` for supported commands.

## Repository Map
- `src/azure_functions_openapi/` package code.
- `tests/` CLI, generation, and utility coverage.
- `examples/` example Azure Functions apps.
- `docs/` documentation site content.

## Issue Authoring

Follow [Repository scope](https://github.com/yeongseon/azure-functions-openapi-python/blob/main/AGENTS.md#repository-scope)
before creating or editing an issue and verify the saved title, body, and labels afterwards.
This also applies when using the API or CLI.

## Change Workflow
1. Confirm whether the change affects runtime API, CLI, schema output, or docs only.
2. Update examples when they are used as public contract material.
3. Keep tests and docs in lockstep for public behavior changes.
4. Do not broaden supported Python versions or dependency ranges casually.
5. Record review evidence per [docs/review-evidence-policy.md](review-evidence-policy.md) in the PR's "Review Evidence" section before merging — advisory, not a required check.

## Validation
- `make doctor` checks tools read-only; func/Azurite are required for live local lanes.
- `make check` runs complete non-mutating lint, format, types, security and policy checks.
- `make test`
- `make integration` starts the real host and an isolated emulator with cleanup.
- `make verify` is the full local gate; `make check-all` is an exact alias.
- `make e2e-azure` separately certifies an explicitly configured deployed candidate.
- `make report` renders saved `test-results/` evidence without rerunning checks.
- `make clean` removes generated artifacts, never `.venv` or shared emulator data.

See [Development Guide](development.md#makefile-targets) for the command contract;
`lint`, `typecheck`, `security`, `build`, `docs`, `perf` and demos are focused/partial.
