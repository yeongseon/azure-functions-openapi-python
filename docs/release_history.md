# Release History and Provenance

This page records how each published version of **azure-functions-openapi** maps to a Git tag, a
GitHub Release and a PyPI distribution, and lists the historical cases where those records do not
line up. The data was reconciled against Git, PyPI and GitHub on 2026-11-10. For how new versions
are released, see [Release Process](release_process.md).

---

## What each record proves

| Record | Proves | Does not prove |
|---|---|---|
| PyPI distribution | The package users install exists, with its files and upload time | Which commit built it (only PyPI attestations, available from `0.12.0`, say so) |
| Git tag | A commit was labelled with a version | That the tagged source is what shipped, or that anything was published |
| GitHub Release | A release page with notes exists | That a package was published |

A GitHub Release is never evidence of publication. Check the
[PyPI release history](https://pypi.org/project/azure-functions-openapi/#history).

---

## Reconciliation summary

| Evidence set | Count |
|---|---:|
| Git tags | 45 |
| PyPI versions (`0.4.0` to `0.31.0`) | 42 |
| GitHub Releases | 42 |

| Category | Versions |
|---|---|
| Published, with a matching tag and GitHub Release | 34 versions: `0.7.0`, `0.8.0`, `0.10.0`, `0.10.1`, `0.12.0`, and every release from `0.14.0` to `0.31.0` except `0.17.2` |
| Published, tag exists, GitHub Release added afterwards | `0.4.0`, `0.5.0`, `0.5.1`, `0.6.0`, `0.6.1`, `0.12.1`, `0.13.1` |
| Published, no tag, no GitHub Release | `0.11.0` |
| Tag only: no PyPI distribution, no GitHub Release | `v0.2.0`, `v0.3.0`, `v0.4.1` |
| Invalid tag with a GitHub Release, never published | `v0.17.2` |

For every published version that has a tag, the package files on PyPI are byte-identical to the
tagged commit (see [How this was verified](#how-this-was-verified)).

---

## Tag-only versions: 0.2.0, 0.3.0 and 0.4.1

The annotated tags `v0.2.0` (commit `5727740`, 2025-05-03), `v0.3.0` (`8578dc8`, 2025-05-07) and
`v0.4.1` (`082958f`, 2025-06-22) are on the history of `main`, each tagged commit declares the
matching `__version__`, and `CHANGELOG.md` has a section for each. PyPI shows no distribution for
any of them. Whether one ever existed cannot be determined from PyPI, so they are classified as
**tag-only** and are not presumed published.

All four early tags (`v0.2.0`, `v0.3.0`, `v0.4.0`, `v0.4.1`) were created together on 2025-06-22
(within 12 seconds), so for `v0.2.0`, `v0.3.0` and `v0.4.0` the tag date is weeks later than the
tagged commit. No GitHub Release is created for the three tag-only versions: a release page would
imply a distributable package that does not exist, and the changelog already describes them.

---

## 0.11.0: published to PyPI without a tag

**Facts**

- PyPI has `0.11.0` (sdist and wheel, first uploaded 2026-02-10 00:57 UTC). It has no Git tag, no
  GitHub Release and no `CHANGELOG.md` section, and no commit in any ref has ever contained
  `__version__ = "0.11.0"`. The [`v0.12.0` release notes](https://github.com/yeongseon/azure-functions-openapi-python/releases/tag/v0.12.0)
  state that its tag and release metadata were not preserved.
- The package files of `0.11.0` were compared with the package directory of all 883 commits
  reachable from any ref. None matches. The closest trees are the `0.10.0` and `0.10.1` package
  sources; each differs from `0.11.0` in exactly one file, `__init__.py`, and only in the version
  string.
- PyPI has no attestation for this file, so no workflow run or commit can be attached to it.

**Timeline (UTC)**

| Time | Event |
|---|---|
| 2026-02-10 00:57:09 | PyPI `0.11.0` uploaded |
| 2026-02-10 01:01:12 | Commits `f41d1be` ("bump version to 0.10.1") and `d62399e` (tagged `v0.10.1`) |
| 2026-02-10 01:01:35 | PyPI `0.10.1` uploaded |

**Interpretation (not proven):** `0.11.0` looks like a mis-numbered minor bump of the `0.10.x`
source that was superseded by `0.10.1` four minutes later.

**Decision:** keep this as a permanent, documented historical exception. No tag or GitHub Release
is created, because no commit carries the `0.11.0` package: tagging any other commit would invent
provenance, and pushing a `v*` tag starts the publish workflow. The PyPI files are not changed.

---

## v0.17.2: invalid tag, never published

**Facts**

- The tag `v0.17.2` is a lightweight tag on commit `a25b33f`
  ("update repo references for azure-functions-{feature}-python naming convention", 2026-04-17).
  That commit declares `__version__ = "0.15.1"`.
- The commit is not part of the history of `main`. It sits on a side branch forked from `main` at
  `c44fa0a` with two commits: `dbeb6dd` ("add automatic GitHub Release creation on tag push") and
  `a25b33f`. GitHub's [`v0.17.1...v0.17.2`](https://github.com/yeongseon/azure-functions-openapi-python/compare/v0.17.1...v0.17.2)
  comparison reports it as *diverged* (2 commits ahead, 38 behind).
- Pushing the tag (2026-04-18 13:28:47 UTC, Actions actor `yeongseon`) started three workflows:
  [`Publish to PyPI`](https://github.com/yeongseon/azure-functions-openapi-python/actions/runs/24605715852)
  (failed), [`e2e-azure`](https://github.com/yeongseon/azure-functions-openapi-python/actions/runs/24605715858)
  (failed) and [`Create GitHub Release`](https://github.com/yeongseon/azure-functions-openapi-python/actions/runs/24605715854)
  (succeeded). The last one created the GitHub Release seven seconds later. That workflow
  (`create-release.yml`) was removed when Release Please was adopted.
- PyPI has no `0.17.2`, `CHANGELOG.md` has no `0.17.2` section, and the next release, `v0.18.0`,
  follows `v0.17.1`. The job logs have expired, so the exact failing step cannot be re-read. A
  version mismatch between the tag and `__version__` is the expected cause but is not confirmed.

**Decision:** the tag is kept unchanged as an audit record and no `0.17.2` package is created. The
GitHub Release body now begins with a notice that it is not a usable release, and the standard
note layout is prevented from presenting the two side-branch commits as release changes. The
notice is a protected statement in `.github/release-notes.json`, so re-rendering cannot drop it.

---

## GitHub Releases added for published versions

These versions were already on PyPI and already had a tag, but no GitHub Release. The Release was
added afterwards on the **existing** tag; no tag, package file or date was changed. Notes are
reconstructed from `CHANGELOG.md` and cross-checked against the commits between the tags.

| Version | PyPI upload (UTC) | Tagged commit | PyPI attestation |
|---|---|---|---|
| `0.4.0` | 2025-05-13 | `fb95c77` | none (predates attestations) |
| `0.5.0` | 2025-09-04 | `a175f91` | none |
| `0.5.1` | 2026-01-21 | `887d0b9` | none |
| `0.6.0` | 2026-01-21 | `5e2eb64` | none |
| `0.6.1` | 2026-01-22 | `e79d8d3` | none |
| `0.12.1` | 2026-03-09 | `0e7e687` | built from the tag at this commit |
| `0.13.1` | 2026-03-14 | `0bc7578` | built from the tag at this commit |

The cross-check found one discrepancy. `CHANGELOG.md` lists *Use working example* (PR #103) under
`0.12.1`, but that commit was made after the `v0.12.1` tag and first shipped in `0.13.1`. The
Release notes follow the commit history, and `CHANGELOG.md` is left as Release Please and
git-cliff wrote it.

GitHub orders Releases by the date of their tag, so each added Release appears next to its
neighbours rather than at the top of the list; the time it was added is recorded as its
publication time. Older Release bodies link to the former repository name
`azure-functions-openapi`; GitHub redirects those URLs, including compare links, to the current
repository.

---

## Checking the history automatically

`make release-audit` re-reads Git tags, GitHub Releases, `CHANGELOG.md` and PyPI and exits
non-zero for any discrepancy that is not an approved exception. It only reads: it never moves,
creates or deletes a tag, a Release or a package. Set `GH_TOKEN` to stay under GitHub's anonymous
rate limit, for example `GH_TOKEN=$(gh auth token) make release-audit`.

| Code | Meaning |
|---|---|
| `TAG_VERSION_MISMATCH` | the tagged source declares a different version than the tag |
| `TAG_NOT_ON_MAINLINE` | the tagged commit is not on the history of `main` |
| `TAG_ONLY` | a tag with neither a PyPI distribution nor a GitHub Release |
| `PYPI_WITHOUT_TAG` | published to PyPI, but no Git tag exists |
| `PYPI_WITHOUT_RELEASE` | published and tagged, but no GitHub Release exists |
| `RELEASE_WITHOUT_PYPI` | a GitHub Release exists, but nothing was published to PyPI |
| `RELEASE_WITHOUT_TAG` | a GitHub Release exists, but its tag does not |
| `CHANGELOG_MISSING` | tagged, released or published, but `CHANGELOG.md` has no section for it |

The approved exceptions are the cases documented on this page, kept in
`.github/release-audit.json` with their reason and a link to the section that explains them. An
exception must match the findings exactly, so one that no longer applies, or no longer covers
everything found for that version, fails the audit instead of going stale. A release younger than
12 hours that is still in the publish gate is reported as pending rather than as a failure. Do not
edit the file to silence a real defect: fix forward, or record the case here with its evidence.

Two narrower commands are used by the release pipeline. `python -m tools.release_audit
check-tag vX.Y.Z` checks that the tagged source declares that version, that the commit is on
`main` and that `CHANGELOG.md` has its section. `check-published vX.Y.Z --wait-minutes N` waits
until PyPI serves the version. Exit codes are 0 for clean, 1 for a discrepancy and 2 when the
audit itself could not run. The full audit also runs weekly in the `Release history audit`
workflow; see [Release verification and alerts](release_process.md#release-verification-and-alerts).

---

## How this was verified

1. **Tag, commit and version.** `git show vX.Y.Z:src/azure_functions_openapi/__init__.py` gives the
   declared `__version__`, and `git merge-base --is-ancestor vX.Y.Z origin/main` tells whether the
   tag is on the history of `main`.
2. **PyPI.** The [JSON API](https://pypi.org/pypi/azure-functions-openapi/json) lists each
   version's files, upload time and yanked state.
3. **PyPI files against the tagged commit.** The snippet below compares the package files in the
   sdist with the package directory at the tag, using Git blob IDs. Run it from a clone that has
   the tags.
4. **PyPI attestations.** For `0.12.0` and later,
   `https://pypi.org/integrity/azure-functions-openapi/<version>/<sdist file>/provenance` returns
   an attestation whose certificate records the source commit and the workflow run. For `0.12.1`
   through `0.31.0` the attested commit equals the tagged commit. `0.12.0` was published from a
   run on `main` at `0d1db8f`, three commits after its tag `8094885`, with identical `src/`.
5. **Workflow runs.** The Actions API keeps run metadata, even after the job logs have expired.

```python
import hashlib
import io
import json
import subprocess
import tarfile
import urllib.request

version, tag = "0.12.1", "v0.12.1"
meta = json.load(
    urllib.request.urlopen(f"https://pypi.org/pypi/azure-functions-openapi/{version}/json")
)
sdist = next(u["url"] for u in meta["urls"] if u["packagetype"] == "sdist")


def blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


shipped = {}
with tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(sdist).read())) as tar:
    for member in tar.getmembers():
        _, found, name = member.name.partition("/azure_functions_openapi/")
        if member.isfile() and found and "__pycache__" not in name:
            shipped[name] = blob_id(tar.extractfile(member).read())

listing = subprocess.run(
    ["git", "ls-tree", "-r", f"{tag}:src/azure_functions_openapi"],
    capture_output=True,
    text=True,
    check=True,
).stdout
tagged = {line.split("\t")[1]: line.split()[2] for line in listing.splitlines()}
print(
    "identical"
    if shipped == tagged
    else sorted(k for k in shipped.keys() | tagged.keys() if shipped.get(k) != tagged.get(k))
)
```

---

## Rules for the future

- Never move or delete a tag, and never re-upload or replace a published file to repair history.
  Record the case here instead.
- Do not create a tag for a commit that did not produce the published package.
- When a GitHub Release is added for an existing tag, say so in its notes. Mark a release that was
  never published as such.
- Use PyPI, not a GitHub Release, to decide whether a version was published.
