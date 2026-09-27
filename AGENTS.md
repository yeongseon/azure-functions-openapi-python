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

### Documentation & Translations
- English (`README.md`) is the **canonical** source of truth for all documentation. Translated READMEs (`README.ko.md`, `README.ja.md`, `README.zh-CN.md`) are **best-effort**, community-maintained, and may lag the English source.
- Translation sync is **not** required in the same PR as an English change, and a PR is **never** blocked by translation drift. Update translations opportunistically; when you do, keep them faithful to the current English source.
- Each translated README carries a staleness banner linking back to the canonical English README. Keep that banner in place so readers always know the translation may be out of date.

## PR Workflow

**Always issue-first.** Before opening any PR:

1. Run `gh issue list` to check whether a tracking issue already exists for the change.
2. If no issue exists, create one following the Issue Conventions below before writing any code.
3. Open the PR only after the issue exists. The PR body **must** include `Closes #N` for every
   issue it resolves — never open a PR that cannot be traced back to an issue.

**Non-negotiable:** a PR without a linked issue will be rejected at review.

**No merge before the review checklist is complete.** Do not merge a PR until every item on its review checklist is checked off; an incomplete checklist blocks merge regardless of CI status.

### Who approves what

`main` requires **one approving review**, dismisses stale reviews on new commits, and requires all conversations resolved. `enforce_admins` is **false**, so administrators can bypass those requirements. With a single maintainer and no second reviewer, that bypass is the routine path for maintainer-authored changes, not a rare exception — see below for the conditions and the evidence every use must record.

**An AI review is not an approval.** Copilot and Codex submit `COMMENTED`, never `APPROVED`, so they never satisfy the requirement. A PR can carry several AI reviews and still have zero approvals. Treat "the AI reviewed it" and "an authorized reviewer accepted it" as separate facts.

**Maintainer-authored PRs have no approver.** GitHub forbids approving your own PR, and `yeongseon` is the only account with push access, so a maintainer-authored PR cannot reach an approved state on the normal path.

**A second reviewer has been declined.** That decision is settled; do not re-propose it as the preferred path. It removes the only option that satisfied the rule as written, which means routine maintainer-authored work has no path that ends in an approval. The rule is not being met — it is being substituted for, and the sections below say exactly what the substitute is.

For a maintainer-authored change, in order of preference:

1. **Split the work.** If the change is genuinely reviewable by a contributor, let them author it so a maintainer can approve. This is the only remaining option that produces a real second pair of eyes, and it is worth reaching for more often than it currently is.
2. **Administrator bypass**, under the procedure below.

**Externally authored PRs are unaffected** and must not use the bypass. A maintainer reviews, approves, and merges them on the normal path. The bypass exists because one specific person cannot approve their own work, not because approval is optional.

Do not silently self-merge. Every bypass carries the evidence comment below, so the substitution stays auditable rather than invisible.

### Administrator bypass

Permitted for a maintainer-authored change that is blocked **solely** by the missing approval. **Never use it to skip a failing check** — that prohibition is absolute and is the one thing this substitution must never erode.

The approval requirement is what is being substituted for; the status checks are what actually guard `main`, so they get stricter, not looser. Before bypassing:

- Query check-runs on the **exact head SHA being merged** (`gh api repos/{owner}/{repo}/commits/{sha}/check-runs`). Confirm zero non-success, zero incomplete, and no required context missing. Do **not** read the PR status rollup instead: a rollup can report a stale success while a newly-started run has not yet replaced it. Two merges on 2026-09-27 broke `main` exactly this way (#628 here, `azure-functions-doctor-python`#463).
- Confirm all review conversations are resolved.
- For an externally authored PR, stop — those do not qualify.

Then record on the PR, in one comment:

- the head SHA merged,
- which requirement was bypassed and why no reviewer was available,
- the CI run that passed on that SHA,
- anything left unverified.

Merge with `gh pr merge --admin --squash --delete-branch`, keeping the `--delete-branch` flag the Branch Hygiene section requires of every CLI merge.

**If a bypass does not meet the conditions above, say so in the evidence comment rather than reframing the change to fit.** An honestly recorded divergence is reviewable; a dressed-up one is not.

**The structural alternative.** Dropping `required_approving_review_count` to 0 — while keeping every required status check and `required_conversation_resolution` — would remove the need for bypass entirely. The approval count currently blocks only the one person who can merge: external contributors cannot self-merge regardless, because they lack push access. Changing it is shared-infrastructure configuration and needs an explicit maintainer decision, so it is documented here as an option, not adopted.

### Dependabot

`dependabot-automerge.yml` enables auto-merge for patch and minor updates using `secrets.GITHUB_TOKEN`. That token cannot approve a PR, so auto-merge alone cannot satisfy the approval requirement — a Dependabot PR still needs a human approval before it can complete.

**This has been exercised, and the fix is an approval.** On 2026-09-27, seven Dependabot PRs across the fleet sat at `REVIEW_REQUIRED` with auto-merge enabled and CI green, some for days. Ordinary maintainer approval cleared all seven; four merged within seconds of the approval landing.

**A Dependabot PR is not a maintainer-authored PR.** Its author is `dependabot[bot]`, so GitHub's self-approval prohibition does not apply and the maintainer can simply approve it. Never use the administrator bypass on one, and do not read a stalled bot queue as evidence that branch protection is unworkable — it means nobody pressed approve. That misreading happened once already.

Review the diff before approving: confirm it is a version bump with no unrelated changes, and that each pinned action SHA matches its claimed tag (`git ls-remote --tags <repo>`, comparing against the dereferenced `^{}` commit).

### Release flow

`make release-*` commits and pushes directly to `main` rather than opening a PR. There is no push allow-list on the branch, so this works **because** `enforce_admins` is false. Keep that in mind before changing the setting: enabling admin enforcement would break the release path until it is reworked to go through a PR.

## Issue Conventions

Follow these conventions when opening issues so the backlog stays consistent with sibling DX Toolkit repositories.

### Title

- Use Conventional Commit prefixes: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `ci:`, `build:`, `perf:`.
- Add a scope qualifier when it narrows the area: `feat(cli):`, `docs(spec):`, `refactor(bridge):`.
- Keep the title imperative, under ~80 characters, no trailing period.
- Do **not** put a priority marker in the title — priority is tracked with a `priority:*` label.

### Body

Use the following sections, in order, omitting any that do not apply:

```
## Context
What problem this issue addresses and why now. Note the target release (e.g. vX.Y.Z) here if known.

## Acceptance Checklist
- [ ] Concrete, verifiable items.

## Out of scope
- Items intentionally excluded, with links to the issues that track them.

## References
- PRs, ADRs, sibling issues, external docs.
```

### Labels

- Apply at least one of `bug`, `enhancement`, `documentation`, `chore`.
- Apply exactly one priority label. The scale in use is `priority:critical` / `priority:high` / `priority:medium` / `priority:low`; `critical` is reserved for defects that reach package users, such as a broken published artifact or wrong product output.
- Labels are applied by maintainers or authorized triage automation. An external contributor without label permissions should describe urgency in the issue body and leave labelling to triage.
- Add `area:*` labels when they exist in the repository.
- Use `blocker` only when the issue blocks a release.

### Umbrella issues

When splitting a large piece of work into focused issues, keep the umbrella open as a tracker that links each child issue with a checkbox; close it once every child is closed or explicitly deferred.

**Single-repo boundary (non-negotiable).** An umbrella issue may only track child issues **in this same repository**. Do **not** open a tracker here that coordinates, checklists, or drives work in sibling repos (`azure-functions-validation-python`, `azure-functions-logging-python`, etc.), and do **not** ask another repo to host a tracker for this one. Each repository in the DX Toolkit is operated **independently** — it owns its own backlog, fix, verification, and release cadence.

- A bug that also exists in sibling repos is **not** one shared work item — it is N independent per-repo issues. File (or ask the maintainer to file) a separate issue in each affected repo; fix and release each on its own timeline.
- Cross-repo audit findings may be **referenced** from a local issue for context (a plain link is fine), but the local issue must be closeable on this repo's work alone. Never leave an issue here open pending another repo's fix.
- If you catch yourself building a checklist of `owner/other-repo#N` items to "drive from here," stop — that is the cross-repo umbrella anti-pattern. Close it as `not planned` and let each repo track its own child issue.

### Issue-creation access (fleet policy)

Keep issue creation **open/unrestricted** on every public toolkit repository (issue tracker enabled, no `interaction-limits`). External bug reports are the only inbound support channel, so restricting issue creation suppresses the signal we most need. Do not enable an interaction limit or restrict issue creation without an explicit, documented reason recorded in an issue first.

### Project management model

This repository is **issue-based, not milestone-based**. Track and group work using issues plus the existing label taxonomy — do **not** introduce parallel structures.

- Plan and group multi-issue efforts with an **umbrella tracker issue** (see above) plus the existing `priority:*` labels. Do **not** create GitHub Milestones — none exist by design, and their absence is an intentional signal, not an oversight.
- Do **not** invent new label taxonomies (e.g. `epic:*`, `vNext`, release-tag labels) to group work. Reuse `priority:*`, `area:*` (only where they already exist), and the umbrella issue. Propose any new label in discussion and wait for explicit approval before creating it.
- Treat optional or tentative suggestions ("we could…", "it might be nice to…", "~해도 괜찮아") as **discussion, not a directive**. Confirm intent before making any structural change to how work is tracked (milestones, labels, project boards, issue hierarchies).
- Before adding any organizational structure, check whether the repository already has an established convention. A category being empty or unused (zero milestones, no `epic:*` labels) is evidence to follow the existing pattern, not to introduce a new one.

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
3. Tag push triggers the **Publish to PyPI** GitHub Actions workflow. **Verification is a pre-publish gate, not a post-publish check.** The `publish` job runs only after `build → lib-tests → cookbook-smoke → cookbook-host-smoke → verify-azure-certification` all pass, and it uploads the exact artifact that was tested (it never rebuilds).
4. Update `docs/changelog.md` separately if needed (different format from `CHANGELOG.md`).

### Tiered runtime verification (what gates a release)

Release verification is layered; each tier catches a different failure class, and **every tier is a pre-publish gate**:

| Tier | Runs where | Catches |
| --- | --- | --- |
| `lib-tests` | publish-pypi.yml (per publish) | library unit regressions |
| `cookbook-smoke` | publish-pypi.yml (per publish) | downstream import/registration drift |
| `cookbook-host-smoke` | publish-pypi.yml (per publish) | candidate wheel installs cleanly and a real `func` host + Azurite boots with it present, no cloud. NOTE: the cookbook HTTP examples do not import this package, so this is a host-boot smoke, **not** proof of this package's own runtime behavior (tracked separately) |
| `verify-azure-certification` | publish-pypi.yml (per publish) | requires a fresh, SHA+version-matched **real-Azure** certification for the exact release commit |
| Azure Release Certification (`e2e-azure.yml`) | `workflow_dispatch`, per release | cloud-only drift — deploys to real Azure, runs live e2e, records a certification artifact. **Certified per release, not per publish.** |

**Real-Azure certification (required once per release, before the final tag).** Before pushing the release tag, dispatch the **e2e-azure** workflow on the exact release commit and version:
- `gh workflow run e2e-azure.yml --ref main -f ref=<release-sha> -f version=<x.y.z>`
- The run deploys to real Azure, executes the live e2e suite, and uploads the `azure-cert` artifact (keyed by commit SHA + version).
- `verify-azure-certification` in `publish-pypi.yml` later requires a successful, SHA+version-matched, non-stale (<14 day) certification for the release commit; without it the publish gate fails and the version stays unpublished.
5. **Verify the release against the dogfood cookbook.** Once **Publish to PyPI** succeeds, confirm the downstream consumer still passes on the freshly published version:
   - In [`azure-functions-cookbook-python`](https://github.com/yeongseon/azure-functions-cookbook-python), upgrade to the new release (`hatch run pip install -U "azure-functions-openapi>=X.Y,<1"`) and run `make test`.
   - Treat any new `RuntimeWarning`/`DeprecationWarning` surfaced by this library during the cookbook run as a release-blocking signal — decorator-order and API-drift problems are reported as warnings, so a clean run (zero warnings from this package) is part of the release gate.
   - If the cookbook pins a lower bound (`azure-functions-openapi>=X.Y,<1`), bump it to the new minor in the same verification PR so examples are tested against the version they advertise.
   - A release is **not** considered done until the cookbook passes on the published version.

## Branch Hygiene

- Merged PR branches are deleted automatically ("Automatically delete head branches" is enabled on this repository); keep that setting on.
- When merging from the CLI, always pass `--delete-branch` (e.g. `gh pr merge --squash --delete-branch`) so the head branch is removed.
- Never delete `main` or `gh-pages`, and never delete a branch that still has an open PR.
- Run `git fetch -p` periodically to prune stale local tracking refs.
