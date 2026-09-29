# Release Checklist

Release Please owns the version, changelog, tag, and GitHub Release; `publish-pypi.yml` owns
verification and the PyPI upload. What is left for a human is review and confirmation.

## Before merging the Release PR

- [ ] CI is green on `main`
- [ ] The proposed version matches intent (`fix:` → patch, `feat:` → minor; pre-1.0 breaking changes stay on `0.x`)
- [ ] The generated `CHANGELOG.md` entry reads correctly — no `fix: fix bug` style entries
- [ ] Documentation updates for this release have already landed on `main`

## After merging

- [ ] `publish-pypi.yml` started from the new tag and every tier passed
      (`build`, `lib-tests`, `cookbook-smoke`, `cookbook-host-smoke`, `azure-e2e`, `publish`)
- [ ] The new version is on PyPI and the GitHub Release exists
- [ ] Dogfood check: the cookbook passes against the published version (see AGENTS.md → Post-release verification)

## If something went wrong

- A failed gate uploads nothing, so the version is still free. Fix and re-run
  `gh workflow run publish-pypi.yml --ref main -f tag=vX.Y.Z`, or fix forward and let the next
  Release PR cut a new version. Never move or reuse a tag.
- No Release PR appearing? First check that `RELEASE_PLEASE_TOKEN` has not expired. Then check for a stale `autorelease: pending` label on an already-merged
  Release PR — Release Please will not open another while one looks in flight, and it reports
  success while doing nothing.
