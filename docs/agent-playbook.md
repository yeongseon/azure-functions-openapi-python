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
and the [Body authoring rules](https://github.com/yeongseon/azure-functions-openapi-python/blob/main/AGENTS.md#body)
in `AGENTS.md` before creating or editing an issue. Human- and agent-authored
issues are held to the same standard. Run a post-save readability pass: verify
the saved title, body, and labels, and confirm an unfamiliar contributor can
answer the four authoring questions (what is broken or missing, why it matters,
what needs to change, and how we know it is done). This also applies when using
the API or CLI.

## Change Workflow
1. Confirm whether the change affects runtime API, CLI, schema output, or docs only.
2. Update examples when they are used as public contract material.
3. Keep tests and docs in lockstep for public behavior changes.
4. Do not broaden supported Python versions or dependency ranges casually.
5. Write a concise PR summary, changes, actual validation and related issue; follow the [PR writing rules](https://github.com/yeongseon/azure-functions-openapi-python/blob/main/AGENTS.md#pull-request-writing). Record additional review details only when needed by [review-evidence-policy.md](review-evidence-policy.md).

## Validation
- `make test`
- `make lint`
- `make typecheck`
- `make security`
- `make build`
