# Review Evidence Policy (advisory)

> **Advisory, not server-enforced.** Nothing here is a required status check. Branch protection
> gates `main` only on the required contexts (`bandit`, `semgrep`, `Analyze`, `PR title`,
> `ci-required`) and conversation resolution; see
> [AGENTS.md "Who approves what"](https://github.com/yeongseon/azure-functions-openapi-python/blob/main/AGENTS.md#who-approves-what).
> Review evidence is a short record a maintainer reads before merging. It adds no bot, verdict
> publisher, check run, or workflow, and it must not be described as an enforced GitHub status.

This is the single source of truth for review expectations. `AGENTS.md`, the playbook and the
pull request template link here instead of restating it.

## Principles

- Review effort scales with risk. Most changes need a compact record; only the high-risk list
  below needs more.
- Copilot, Codex, Claude, OpenCode and human reviewers are interchangeable **review sources**.
  No specific tool, subscription or number of review rounds is required. An external contributor
  can follow this process with no AI reviewer: record "no automated review" and a maintainer
  reviews the diff.
- Required CI and human ownership are unchanged. An AI review is never an approval, and its
  state (`COMMENTED`, or `APPROVED` in Copilot's opt-in preview) does not prove a person accepted
  the change.
- For normal changes, do not request a re-review when a push adds no new material risk (rebase,
  typo, formatting). High-risk changes are different: see below.

## Normal changes (docs, tests, low-risk fixes)

Use the ordinary PR sections: `Summary`, `Changes`, `Validation`, and `Related Issues`.
Report the tests actually run, substantive review findings (if any), and the
maintainer decision when it matters. Do not add empty review-evidence fields,
agent transcripts, or unverifiable claims of approval.

Example:

```text
Validation: make check-all (passed locally); GitHub CI pending.
Review: Removed an unused import identified during review.
```

## High-risk changes

These need a review of the **current head commit** by a source other than the implementer (the
"review unavailable" exception below still applies), and an explicit maintainer review decision.
If a push, including a rebase, changes the head after that review, the review must be refreshed
on the new head:

- Workflow permissions (`permissions:` blocks, `GITHUB_TOKEN` scope, secrets use).
- Release and publishing configuration (`publish-pypi.yml`, `release-please.yml`, PyPI Trusted
  Publishing).
- Swagger UI credential and CSP handling in `docs_routes.py` / `swagger_ui.py`
  (`docs/security.md`), and CLI import trust (`docs/cli.md`; `--app` executes arbitrary module
  code without a sandbox).
- Policy-bearing files: `AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md`, this document, the pull
  request template, `docs/agent-playbook.md`, `docs/release_process.md`, `DESIGN.md`, and the
  safety policy in `docs/security.md`.

Record: the review source, the commit SHA it evaluated, remaining substantive findings, and the maintainer who approved the change and on which commit. A token, an automatic comment, the merge actor, or a green
CI run does not by itself identify that person.

## Which commit was reviewed

A review is evidence for the commit it evaluated, not for the PR as a whole.

- Read the formal review's `commit_id`. For inline comments use `original_commit_id`; GitHub moves
  `commit_id` to the latest push.
- A reply in an existing thread, including one by the PR author, is not a new review.
- A push after a review makes that review stale for the new head. A resolved thread or green CI
  from an older commit does not stand in for it.
- A missing or unknown result means "no evidence", never "approved".

`tools/classify_review_evidence.py` encodes these rules for anyone scripting the check.

## Documented exceptions

These stay visible as exceptions rather than being recorded as reviews:

- **Release Please PRs:** version and changelog only.
- **Dependabot `pip` patch/minor:** auto-merged on green required CI; see
  [AGENTS.md "Dependabot"](https://github.com/yeongseon/azure-functions-openapi-python/blob/main/AGENTS.md#dependabot).
- **GitHub Actions SHA updates:** never auto-merged; the maintainer's check that each pinned SHA
  matches its claimed tag is the evidence, so record that comparison.
- **Review unavailable** (fork PR, quota, outage): record that explicitly and rely on the
  maintainer's own review. Do not leave the field blank.

## Schema and discovery changes

Note the OpenAPI version, Pydantic or SDK contract involved, the expected output or route
behavior, and the tests that prove it. Keep "the document is schema-valid" separate from
"the instance or route behaves correctly"; a valid document is not proof of either.

## Rollout

This stays advisory unless a trusted verdict publisher is identified, bound to a required check in
branch protection, and its bypass rules are documented in `AGENTS.md`. Until then it does not
override the required CI contexts or conversation resolution.
