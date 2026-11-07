from __future__ import annotations

import argparse
from dataclasses import dataclass, field

import pytest

from tools import release_notes as rn

CFG = rn.Config(
    repo="acme/pkg",
    legacy_repos=["acme/old-pkg"],
    non_human_logins={"agent-bot-user"},
    protected={"v1.0.0": ["Not published to PyPI"]},
)


@dataclass
class FakeGitHub:
    tags: list[tuple[str, str]] = field(
        default_factory=lambda: [
            ("v0.9.0", "2026-01-01T00:00:00Z"),
            ("v1.0.0", "2026-02-01T00:00:00Z"),
            ("v1.0.1", "2026-02-02T00:00:00Z"),
        ]
    )
    commits: dict[tuple[str, str], list[rn.Commit]] = field(default_factory=dict)
    prs: dict[int, tuple[str, bool]] = field(default_factory=dict)
    veterans: set[str] = field(default_factory=lambda: {"maint"})
    bodies: dict[str, str] = field(default_factory=dict)

    def releases(self) -> list[tuple[str, str]]:
        return self.tags

    def release_body(self, tag: str) -> str:
        return self.bodies[tag]

    def compare(self, base: str, head: str) -> list[rn.Commit]:
        return self.commits.get((base, head), [])

    def pr_authors(self) -> dict[int, tuple[str, bool]]:
        return self.prs

    def had_prior_contribution(self, login: str, before_tag: str) -> bool:
        return login in self.veterans

    def set_body(self, tag: str, body: str) -> None:
        self.bodies[tag] = body


def commit(sha: str, subject: str, login: str | None, trailer: str = "") -> rn.Commit:
    message = subject + (f"\n\n{trailer}" if trailer else "")
    return rn.Commit(sha=sha * 40, subject=subject, message=message, login=login)


RP_BODY = """## [1.0.1](https://github.com/acme/pkg/compare/v1.0.0...v1.0.1) (2026-02-02)


### Bug Fixes

* **cli:** reject empty suffix ([#12](https://github.com/acme/pkg/issues/12)) ([aaaaaaa](https://github.com/acme/pkg/commit/aaaaaaa))
"""


def test_patch_release_credits_pr_author_and_has_no_contributor_section() -> None:
    gh = FakeGitHub(prs={12: ("maint", False)})
    body = rn.build_notes("v1.0.1", RP_BODY, gh, CFG)
    assert body.startswith("## v1.0.1 (2026-02-02)\n")
    assert "### Bug Fixes" in body
    assert "- **cli:** reject empty suffix (#12) by @maint" in body
    assert "New Contributors" not in body
    assert "**Full Changelog**: https://github.com/acme/pkg/compare/v1.0.0...v1.0.1" in body
    assert body.rstrip().endswith(rn.MARKER)


def test_feature_release_orders_sections_and_omits_empty_ones() -> None:
    original = (
        "## [1.0.0](x) (2026-02-01)\n\n### Bug Fixes\n\n* fix a (#2)\n\n"
        "### Features\n\n* **api:** add b (#1)\n\n### Documentation\n\n* docs: c (#3)\n"
    )
    gh = FakeGitHub(prs={1: ("maint", False), 2: ("maint", False), 3: ("maint", False)})
    body = rn.build_notes("v1.0.0", original + "\nNot published to PyPI\n", gh, CFG)
    assert body.index("### Features") < body.index("### Bug Fixes")
    assert "### Performance" not in body and "### Breaking Changes" not in body
    assert "<details><summary>Documentation, maintenance and other changes (1)" in body
    assert "Not published to PyPI" in body


def test_breaking_change_keeps_upgrade_guidance() -> None:
    original = (
        "## What's Changed\n\n### Breaking\n- Drop v1 support (#5)\n\n"
        "### Upgrade\nRun `pip install -U pkg` and rename `foo` to `bar`.\n\n"
        "### Added\n- thing (#6)\n"
    )
    gh = FakeGitHub(prs={5: ("maint", False), 6: ("maint", False)})
    body = rn.build_notes("v1.0.1", original, gh, CFG)
    assert "### \u26a0\ufe0f Breaking Changes" in body
    assert body.index("Drop v1 support") < body.index("rename `foo` to `bar`")
    assert body.index("rename `foo`") < body.index("### Features")
    assert "#### Upgrade" in body  # keeps the original heading so existing anchors still resolve


def test_first_time_contributor_only_when_verified() -> None:
    gh = FakeGitHub(
        commits={
            ("v1.0.0", "v1.0.1"): [
                commit("a", "fix: handle x (#12)", "newbie"),
                commit("b", "fix: handle y (#13)", "maint"),
                commit("c", "chore(deps): bump z (#14)", "dependabot[bot]"),
                commit("d", "fix: agent tweak (#15)", "agent-bot-user"),
            ]
        },
        prs={12: ("newbie", False), 13: ("maint", False)},
    )
    body = rn.build_notes("v1.0.1", "### Bug Fixes\n- fix x (#12)\n- fix y (#13)\n", gh, CFG)
    assert "- @newbie made their first contribution in #12" in body
    assert "@maint made their first" not in body
    assert "dependabot" not in body and "agent-bot-user" not in body


def test_bots_and_non_human_accounts_are_never_credited() -> None:
    gh = FakeGitHub(prs={1: ("app/dependabot", True), 2: ("agent-bot-user", False)})
    body = rn.build_notes("v1.0.1", "- bump a (#1)\n- tweak b (#2)\n", gh, CFG)
    assert " by @" not in body


def test_coauthor_credit_requires_noreply_address() -> None:
    gh = FakeGitHub(
        commits={
            ("v1.0.0", "v1.0.1"): [
                commit(
                    "a",
                    "fix: z (#20)",
                    "maint",
                    "Co-authored-by: Real <77+realperson@users.noreply.github.com>\n"
                    "Co-authored-by: Guess <someone@example.com>\n"
                    "Co-authored-by: Agent <12+agent-bot-user@users.noreply.github.com>",
                )
            ]
        },
        prs={20: ("maint", False)},
        veterans={"maint", "realperson"},
    )
    body = rn.build_notes("v1.0.1", "### Bug Fixes\n- z (#20)\n", gh, CFG)
    assert "(#20) by @maint, @realperson" in body
    assert "someone" not in body and "agent-bot-user" not in body


def test_compare_only_release_is_reconstructed_and_labelled() -> None:
    gh = FakeGitHub(
        commits={
            ("v1.0.0", "v1.0.1"): [
                commit("a", "fix(core): tolerate empty input (#30)", "maint"),
                commit("b", "chore(main): release 1.0.1", "maint"),
            ]
        },
        prs={30: ("maint", False)},
    )
    original = "<!-- generated -->\n\n**Full Changelog**: https://github.com/acme/old-pkg/compare/v1.0.0...v1.0.1\n"
    body = rn.build_notes("v1.0.1", original, gh, CFG)
    assert "reconstructed from the commits in `v1.0.0...v1.0.1`" in body
    assert "**core:** tolerate empty input (#30) by @maint" in body
    assert "release 1.0.1" not in body


def test_unrecoverable_release_says_so_instead_of_inventing() -> None:
    body = rn.build_notes(
        "v1.0.1", "**Full Changelog**: x/compare/v1.0.0...v1.0.1", FakeGitHub(), CFG
    )
    assert "No user-facing changes could be reconstructed" in body


def test_github_generated_notes_are_normalised_and_legacy_links_rewritten() -> None:
    original = (
        "Not published to PyPI\n\n## What's Changed\n"
        "* feat(x): add thing by @maint in https://github.com/acme/old-pkg/pull/7\n"
        "## New Contributors\n"
        "* @someone made their first contribution in https://github.com/acme/old-pkg/pull/8\n"
        "**Full Changelog**: https://github.com/acme/old-pkg/compare/v0.9.0...v1.0.0\n"
    )
    body = rn.build_notes("v1.0.0", original, FakeGitHub(prs={7: ("maint", False)}), CFG)
    assert "- **x:** add thing (#7) by @maint" in body
    assert "old-pkg" not in body
    assert "@someone" not in body  # unverified claim is dropped, not repeated


def test_losing_a_pr_reference_or_protected_phrase_is_refused() -> None:
    assert rn.verify("- a (#1)\n- b (#2)", "- a (#1)", "v1.0.1", CFG)
    assert rn.verify("x", "## v1.0.0\n", "v1.0.0", CFG) == [
        "protected phrase missing: 'Not published to PyPI'"
    ]


def test_rendering_is_idempotent() -> None:
    gh = FakeGitHub(prs={12: ("maint", False), 13: ("maint", False)})
    original = (
        "### Features\n- feat: add a (#12)\n### Documentation\n- docs(x): b (#13)\n"
        "### Breaking\n- gone (#14)\n### Notes\nStatus: fine.\n"
    )
    once = rn.build_notes("v1.0.1", original, gh, CFG)
    twice = rn.build_notes("v1.0.1", once, gh, CFG)
    assert once == twice


def test_apply_is_skipped_once_standardised_and_backs_up_nothing_unneeded(
    capsys: pytest.CaptureFixture[str],
) -> None:
    gh = FakeGitHub(prs={12: ("maint", False)}, bodies={"v1.0.1": RP_BODY})
    args = argparse.Namespace(tag="v1.0.1", dry_run=False, force=False, backup=None)
    assert rn.cmd_apply(args, CFG, gh) == 0
    first = gh.bodies["v1.0.1"]
    assert rn.MARKER in first
    assert rn.cmd_apply(args, CFG, gh) == 0
    assert gh.bodies["v1.0.1"] == first
    assert "already standardized" in capsys.readouterr().out


def test_unverifiable_first_contribution_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    client = rn.GhCli("acme/pkg")

    def boom(*args: str, stdin: str | None = None) -> str:
        raise subprocess.CalledProcessError(1, ["gh", *args])

    monkeypatch.setattr(client, "_run", boom)
    # API failure must never turn into "first contribution"
    assert client.had_prior_contribution("someone", "v1.0.0") is True


def test_annotations_are_added_once_and_survive_rerender() -> None:
    cfg = rn.Config(
        repo="acme/pkg",
        annotations={
            "v1.0.1": {
                "highlights": ["- Opt-in secure mode (defence in depth, not a guarantee)."],
                "upgrade": ["Use `make_normalizer(...)` instead of the default normalizer."],
            }
        },
    )
    gh = FakeGitHub(prs={1: ("maint", False)})
    once = rn.build_notes("v1.0.1", "### Breaking\n- change (#1)\n", gh, cfg)
    twice = rn.build_notes("v1.0.1", once, gh, cfg)
    assert once == twice
    assert once.count("Opt-in secure mode") == 1
    assert "make_normalizer" in once and "### Highlights" in once
