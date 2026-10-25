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
5. Write a concise PR summary, changes, actual validation and related issue; follow the [PR writing rules](../AGENTS.md#pull-request-writing). Record additional review details only when needed by [review-evidence-policy.md](review-evidence-policy.md).

## Validation
- `make test`
- `make lint`
- `make typecheck`
- `make security`
- `make build`
