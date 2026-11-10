from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import http.client
import json
from pathlib import Path
import re
from typing import Any

import pytest

from tools import release_audit as ra

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
OLD = NOW - timedelta(days=30)
ROOT = Path(__file__).resolve().parents[1]


def tag(
    version: str,
    declared: str | None = None,
    on_mainline: bool = True,
    when: datetime = OLD,
) -> ra.TagFact:
    return ra.TagFact(
        name=f"v{version}",
        commit=("a" * 40),
        committed_at=when,
        declared_version=version if declared is None else declared,
        on_mainline=on_mainline,
    )


def release(version: str, when: datetime = OLD) -> ra.ReleaseFact:
    return ra.ReleaseFact(tag=f"v{version}", prerelease=False, published_at=when)


def pypi(version: str, when: datetime = OLD, yanked: bool = False) -> ra.PyPIFact:
    return ra.PyPIFact(version=version, yanked=yanked, first_upload=when)


@dataclass
class FakeSources:
    tags: list[ra.TagFact] = field(default_factory=list)
    release_list: list[ra.ReleaseFact] = field(default_factory=list)
    pypi_list: list[ra.PyPIFact] = field(default_factory=list)
    changelog: frozenset[str] = frozenset()
    changelog_at: dict[str, frozenset[str]] = field(default_factory=dict)
    pypi_polls: list[list[ra.PyPIFact]] = field(default_factory=list)
    error: ra.AuditError | None = None

    def tag_facts(self) -> list[ra.TagFact]:
        if self.error:
            raise self.error
        return self.tags

    def tag(self, name: str) -> ra.TagFact | None:
        return next((t for t in self.tags if t.name == name), None)

    def releases(self) -> list[ra.ReleaseFact]:
        return self.release_list

    def pypi(self) -> list[ra.PyPIFact]:
        if self.pypi_polls:
            return self.pypi_polls.pop(0) if len(self.pypi_polls) > 1 else self.pypi_polls[0]
        return self.pypi_list

    def changelog_versions(self, ref: str | None = None) -> frozenset[str]:
        return self.changelog_at.get(ref or "", self.changelog)


def config(**approved: tuple[set[str], str]) -> ra.Config:
    return ra.Config(
        repo="acme/pkg",
        package="pkg",
        approved={v: ra.Approved(frozenset(c), r) for v, (c, r) in approved.items()},
    )


def run(cfg: ra.Config, sources: FakeSources, grace: float | None = None) -> ra.Report:
    return ra.audit(cfg, ra.collect(cfg, sources), NOW, grace)


def good(version: str = "1.0.0") -> FakeSources:
    return FakeSources(
        tags=[tag(version)],
        release_list=[release(version)],
        pypi_list=[pypi(version)],
        changelog=frozenset({version}),
    )


def codes_of(report: ra.Report, version: str, kind: str = "unapproved") -> tuple[str, ...]:
    finding = next(f for f in report.findings if f.version == version)
    result: tuple[str, ...] = getattr(finding, kind)
    return result


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


# ------------------------------------------------------------ the six fixture cases from #904


def test_matching_release_is_clean() -> None:
    report = run(config(), good())
    assert report.ok
    assert report.findings == ()
    assert report.counts == {
        "tags": 1,
        "github_releases": 1,
        "pypi_versions": 1,
        "changelog_sections": 1,
    }


def test_incorrect_tagged_version_is_flagged() -> None:
    sources = good("1.0.1")
    sources.tags = [tag("1.0.1", declared="1.0.0")]
    report = run(config(), sources)
    assert not report.ok
    assert codes_of(report, "1.0.1") == (ra.TAG_VERSION_MISMATCH,)


def test_divergent_tag_is_flagged() -> None:
    sources = good("1.0.1")
    sources.tags = [tag("1.0.1", on_mainline=False)]
    report = run(config(), sources)
    assert not report.ok
    assert codes_of(report, "1.0.1") == (ra.TAG_NOT_ON_MAINLINE,)


def test_pypi_version_without_github_release_is_flagged() -> None:
    sources = good()
    sources.release_list = []
    report = run(config(), sources)
    assert not report.ok
    assert codes_of(report, "1.0.0") == (ra.PYPI_WITHOUT_RELEASE,)


def test_pypi_version_without_a_tag_is_flagged() -> None:
    sources = good()
    sources.tags = []
    sources.release_list = []
    report = run(config(), sources)
    assert codes_of(report, "1.0.0") == (ra.PYPI_WITHOUT_TAG,)


def test_github_release_without_pypi_publication_is_flagged() -> None:
    sources = good()
    sources.pypi_list = []
    report = run(config(), sources)
    assert not report.ok
    assert codes_of(report, "1.0.0") == (ra.RELEASE_WITHOUT_PYPI,)


def test_github_release_without_its_tag_is_flagged() -> None:
    sources = good()
    sources.tags = []
    sources.pypi_list = []
    report = run(config(), sources)
    assert codes_of(report, "1.0.0") == (ra.RELEASE_WITHOUT_TAG,)


def test_intentionally_tag_only_history_is_allowed_only_when_approved() -> None:
    sources = FakeSources(tags=[tag("0.2.0")], changelog=frozenset({"0.2.0"}))
    assert not run(config(), sources).ok
    approved = config(**{"0.2.0": ({ra.TAG_ONLY}, "retroactive tag, never published")})
    report = run(approved, sources)
    assert report.ok
    assert codes_of(report, "0.2.0", "approved") == (ra.TAG_ONLY,)
    assert report.findings[0].reason == "retroactive tag, never published"


# ------------------------------------------------------------ exceptions, grace and changelog


def test_approved_exception_must_cover_every_finding() -> None:
    sources = good("1.0.1")
    sources.tags = [tag("1.0.1", declared="1.0.0", on_mainline=False)]
    partial = config(**{"1.0.1": ({ra.TAG_VERSION_MISMATCH}, "known")})
    report = run(partial, sources)
    assert not report.ok
    assert codes_of(report, "1.0.1", "approved") == (ra.TAG_VERSION_MISMATCH,)
    assert codes_of(report, "1.0.1") == (ra.TAG_NOT_ON_MAINLINE,)


def test_stale_exception_is_reported_instead_of_rotting() -> None:
    stale = config(**{"1.0.0": ({ra.PYPI_WITHOUT_RELEASE}, "was missing, since restored")})
    report = run(stale, good())
    assert not report.ok
    assert codes_of(report, "1.0.0", "stale") == (ra.PYPI_WITHOUT_RELEASE,)


def test_exception_for_a_version_that_no_longer_exists_is_stale() -> None:
    report = run(config(**{"9.9.9": ({ra.TAG_ONLY}, "gone")}), good())
    assert not report.ok
    assert codes_of(report, "9.9.9", "stale") == (ra.TAG_ONLY,)


def test_missing_changelog_section_is_flagged() -> None:
    sources = good()
    sources.changelog = frozenset()
    assert codes_of(run(config(), sources), "1.0.0") == (ra.CHANGELOG_MISSING,)


def test_young_release_still_publishing_is_pending_not_failing() -> None:
    fresh = NOW - timedelta(hours=1)
    sources = FakeSources(
        tags=[tag("1.0.0", when=fresh)],
        release_list=[release("1.0.0", when=fresh)],
        changelog=frozenset({"1.0.0"}),
    )
    report = run(config(), sources)
    assert report.ok
    assert codes_of(report, "1.0.0", "pending") == (ra.RELEASE_WITHOUT_PYPI,)
    assert not run(config(), sources, grace=0).ok


def test_a_wrong_version_is_never_pending_even_when_young() -> None:
    fresh = NOW - timedelta(minutes=5)
    sources = FakeSources(
        tags=[tag("1.0.1", declared="1.0.0", when=fresh)],
        release_list=[release("1.0.1", when=fresh)],
        changelog=frozenset({"1.0.1"}),
    )
    report = run(config(), sources)
    assert not report.ok
    assert codes_of(report, "1.0.1") == (ra.TAG_VERSION_MISMATCH,)
    assert codes_of(report, "1.0.1", "pending") == (ra.RELEASE_WITHOUT_PYPI,)


def test_versions_are_reported_in_numeric_order() -> None:
    sources = FakeSources(
        tags=[tag("0.10.0"), tag("0.9.0"), tag("0.2.0")],
        changelog=frozenset({"0.10.0", "0.9.0", "0.2.0"}),
    )
    report = run(config(), sources)
    assert [f.version for f in report.findings] == ["0.2.0", "0.9.0", "0.10.0"]


# ------------------------------------------------------------ rendering and configuration


def test_text_and_json_reports_agree() -> None:
    sources = FakeSources(tags=[tag("0.2.0")], changelog=frozenset({"0.2.0"}))
    report = run(config(), sources)
    text = ra.render(report, 12)
    assert "UNAPPROVED discrepancies: 1" in text
    assert "0.2.0" in text and ra.TAG_ONLY in text
    assert "RESULT: DISCREPANCIES FOUND" in text
    data = json.loads(ra.to_json(report))
    assert data["ok"] is False
    assert data["findings"][0]["unapproved"] == [ra.TAG_ONLY]


def write(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_config_rejects_unknown_codes_missing_reason_and_missing_keys(tmp_path: Path) -> None:
    base: dict[str, Any] = {"repo": "a/b", "package": "b"}
    bad_code = {**base, "approved": {"1.0.0": {"codes": ["NOPE"], "reason": "x"}}}
    no_reason = {**base, "approved": {"1.0.0": {"codes": [ra.TAG_ONLY], "reason": " "}}}
    for data in (bad_code, no_reason, {"repo": "a/b"}):
        with pytest.raises(ra.AuditError):
            ra.Config.load(write(tmp_path / "c.json", data))
    with pytest.raises(ra.AuditError):
        ra.Config.load(tmp_path / "missing.json")
    assert ra.Config.load(write(tmp_path / "ok.json", base)).package == "b"


def heading_slug(heading: str) -> str:
    """GitHub's anchor for a Markdown heading: lower case, punctuation dropped, spaces to dashes."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def test_committed_exceptions_are_valid_and_point_at_documented_sections() -> None:
    cfg = ra.Config.load(ROOT / ra.CONFIG_PATH)
    docs = (ROOT / "docs" / "release_history.md").read_text(encoding="utf-8")
    anchors = {heading_slug(m[1]) for m in re.finditer(r"^#{2,4} (.+)$", docs, re.MULTILINE)}
    assert cfg.approved, "the historical exceptions must be listed"
    for version, entry in cfg.approved.items():
        assert re.fullmatch(r"\d+\.\d+\.\d+", version)
        assert entry.reason.strip()
        path, _, anchor = entry.ref.partition("#")
        assert path == "docs/release_history.md", version
        assert anchor in anchors, f"{version}: no heading for #{anchor}"


# ------------------------------------------------------------ single-tag checks


def test_check_tag_accepts_a_sound_release_tag() -> None:
    sources = good("1.2.3")
    sources.changelog_at = {"a" * 40: frozenset({"1.2.3"})}
    assert ra.check_tag("v1.2.3", config(), sources) == []


def test_check_tag_reports_every_problem() -> None:
    sources = FakeSources(tags=[tag("1.2.3", declared="1.2.0", on_mainline=False)])
    problems = ra.check_tag("v1.2.3", config(), sources)
    assert len(problems) == 3
    assert any("declares version '1.2.0', not '1.2.3'" in p for p in problems)
    assert any("not on the history of main" in p for p in problems)
    assert any("no section for 1.2.3" in p for p in problems)


def test_check_tag_rejects_non_release_and_missing_tags() -> None:
    assert "not a release tag" in ra.check_tag("latest", config(), FakeSources())[0]
    assert "v1.2.3 does not exist" in ra.check_tag("v1.2.3", config(), FakeSources())[0]


def test_check_tag_waits_for_a_tag_the_api_does_not_show_yet() -> None:
    clock = Clock()
    sources = good("1.2.3")
    sources.changelog_at = {"a" * 40: frozenset({"1.2.3"})}
    visible = sources.tags
    appears = iter([[], [], visible])

    class Late(FakeSources):
        def tag(self, name: str) -> ra.TagFact | None:
            self.tags = next(appears)
            return super().tag(name)

    late = Late(changelog_at=sources.changelog_at)
    assert ra.check_tag("v1.2.3", config(), late, 60, clock.sleep, clock.monotonic) == []
    assert clock.sleeps == [5.0, 5.0]


def test_check_tag_gives_up_waiting_but_reports_other_problems_at_once() -> None:
    clock = Clock()
    problems = ra.check_tag("v1.2.3", config(), FakeSources(), 12, clock.sleep, clock.monotonic)
    assert problems == ["tag v1.2.3 does not exist"]
    assert sum(clock.sleeps) == 12
    wrong = FakeSources(tags=[tag("1.2.3", declared="1.2.0")])
    quiet = Clock()
    assert ra.check_tag("v1.2.3", config(), wrong, 60, quiet.sleep, quiet.monotonic)
    assert quiet.sleeps == []


# ------------------------------------------------------------ waiting for PyPI


def test_check_published_succeeds_as_soon_as_pypi_serves_the_version() -> None:
    clock = Clock()
    sources = FakeSources(pypi_polls=[[], [], [pypi("1.0.0")]])
    assert ra.check_published("v1.0.0", config(), sources, 5, 30, clock.sleep, clock.monotonic)
    assert clock.sleeps == [30, 30]


def test_check_published_gives_up_at_the_deadline() -> None:
    clock = Clock()
    sources = FakeSources(pypi_polls=[[]])
    assert not ra.check_published("v1.0.0", config(), sources, 2, 30, clock.sleep, clock.monotonic)
    assert sum(clock.sleeps) == 120


def test_check_published_does_not_count_a_yanked_version() -> None:
    sources = FakeSources(pypi_list=[pypi("1.0.0", yanked=True)])
    clock = Clock()
    assert not ra.check_published("v1.0.0", config(), sources, 0, 1, clock.sleep, clock.monotonic)


# ------------------------------------------------------------ command line


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    return write(tmp_path / "audit.json", {"repo": "acme/pkg", "package": "pkg"})


def cli(config_file: Path, sources: FakeSources, *args: str, clock: Clock | None = None) -> int:
    sleep = clock.sleep if clock else (lambda _seconds: None)
    return ra.main(["--config", str(config_file), *args], sources=sources, now=NOW, sleep=sleep)


def test_audit_command_exit_codes(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(config_file, good(), "audit") == 0
    assert "RESULT: OK" in capsys.readouterr().out
    broken = good()
    broken.pypi_list = []
    assert cli(config_file, broken, "audit") == 1
    assert "RELEASE_WITHOUT_PYPI" in capsys.readouterr().out
    assert cli(config_file, broken, "audit", "--json") == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_audit_command_fails_closed_when_it_cannot_run(
    config_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    unreachable = FakeSources(error=ra.AuditError("api.github.com is down"))
    assert cli(config_file, unreachable, "audit") == 2
    assert "could not run" in capsys.readouterr().err
    assert ra.main(["--config", str(tmp_path / "nope.json"), "audit"]) == 2


def test_check_tag_command(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sound = good("1.2.3")
    sound.changelog_at = {"a" * 40: frozenset({"1.2.3"})}
    assert cli(config_file, sound, "check-tag", "v1.2.3") == 0
    assert "agree" in capsys.readouterr().out
    wrong = FakeSources(tags=[tag("1.2.3", declared="1.2.0")])
    assert cli(config_file, wrong, "check-tag", "v1.2.3") == 1
    assert "declares version '1.2.0'" in capsys.readouterr().err


def test_check_published_command(config_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(config_file, good(), "check-published", "v1.0.0") == 0
    assert "published on PyPI" in capsys.readouterr().out
    assert cli(config_file, FakeSources(), "check-published", "v1.0.0") == 1
    assert "not proof of publication" in capsys.readouterr().err


# ------------------------------------------------------------ live sources over a fake client


class FakeClient:
    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.seen: list[str] = []

    def json(self, path: str, optional: bool = False) -> Any:
        self.seen.append(path)
        if path not in self.routes:
            if optional:
                return None
            raise ra.AuditError(f"unexpected GET {path}")
        return self.routes[path]

    def text(self, path: str) -> str | None:
        self.seen.append(path)
        value = self.routes.get(path)
        return None if value is None else str(value)

    def pages(self, path: str) -> list[Any]:
        self.seen.append(path)
        return list(self.routes[path])


def live(
    github: FakeClient, pypi_client: FakeClient | None = None, cfg: ra.Config | None = None
) -> ra.LiveSources:
    return ra.LiveSources(cfg or config(), "", github, pypi_client)


def test_live_tag_reads_commit_declared_version_and_mainline() -> None:
    sha = "b" * 40
    github = FakeClient(
        {
            "/repos/acme/pkg/commits/v1.0.0": {
                "sha": sha,
                "commit": {"committer": {"date": "2026-01-02T03:04:05Z"}},
            },
            "/repos/acme/pkg/contents/azure_functions_openapi/__init__.py?ref=" + sha: (
                'x = 1\n__version__ = "1.0.0"\n'
            ),
            "/repos/acme/pkg/commits?sha=main&per_page=100&page=1": [{"sha": sha}],
        }
    )
    both_layouts = ra.Config(
        repo="acme/pkg",
        package="pkg",
        version_files=(
            "src/azure_functions_openapi/__init__.py",
            "azure_functions_openapi/__init__.py",
        ),
    )
    sources = live(github, cfg=both_layouts)
    fact = sources.tag("v1.0.0")
    assert fact == ra.TagFact(
        "v1.0.0", sha, datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "1.0.0", True
    )
    assert sources.tag("v9.9.9") is None


def test_live_mainline_membership_pages_until_found_or_exhausted() -> None:
    first = [{"sha": f"{i:040x}"} for i in range(100)]
    github = FakeClient(
        {
            "/repos/acme/pkg/commits?sha=main&per_page=100&page=1": first,
            "/repos/acme/pkg/commits?sha=main&per_page=100&page=2": [{"sha": "c" * 40}],
        }
    )
    sources = live(github)
    assert sources._on_mainline(f"{5:040x}")
    assert len(github.seen) == 1  # found on the first page, no second request
    assert sources._on_mainline("c" * 40)
    assert not sources._on_mainline("d" * 40)
    assert len(github.seen) == 2  # history exhausted; nothing more is requested


def test_live_declared_version_is_none_when_file_or_marker_is_missing() -> None:
    sha = "e" * 40
    sources = live(FakeClient({}))
    assert sources._declared_version(sha) is None
    path = f"/repos/acme/pkg/contents/src/azure_functions_openapi/__init__.py?ref={sha}"
    github = FakeClient({path: "no version here"})
    assert live(github)._declared_version(sha) is None


def test_live_tag_facts_keep_only_release_tags_in_version_order() -> None:
    def ref(name: str) -> dict[str, str]:
        return {"ref": f"refs/tags/{name}"}

    sha = "f" * 40
    routes: dict[str, Any] = {
        "/repos/acme/pkg/git/matching-refs/tags/v": [
            ref("v0.10.0"),
            ref("v0.2.0"),
            ref("vnext"),
            ref("v1.0.0-rc1"),
        ],
        "/repos/acme/pkg/commits?sha=main&per_page=100&page=1": [{"sha": sha}],
    }
    for name in ("v0.2.0", "v0.10.0"):
        routes[f"/repos/acme/pkg/commits/{name}"] = {
            "sha": sha,
            "commit": {"committer": {"date": "2026-01-01T00:00:00Z"}},
        }
    names = [t.name for t in live(FakeClient(routes)).tag_facts()]
    assert names == ["v0.2.0", "v0.10.0"]


def test_live_releases_skip_drafts_and_pypi_skips_empty_or_reads_yanked() -> None:
    github = FakeClient(
        {
            "/repos/acme/pkg/releases": [
                {
                    "tag_name": "v1.0.0",
                    "draft": False,
                    "prerelease": False,
                    "published_at": "2026-01-01T00:00:00Z",
                },
                {"tag_name": "v1.1.0", "draft": True, "prerelease": False, "published_at": None},
            ]
        }
    )
    assert [r.tag for r in live(github).releases()] == ["v1.0.0"]
    index = FakeClient(
        {
            "/pypi/pkg/json": {
                "releases": {
                    "1.0.0": [
                        {"yanked": False, "upload_time_iso_8601": "2026-01-02T00:00:00.500000Z"},
                        {"yanked": False, "upload_time_iso_8601": "2026-01-01T00:00:00Z"},
                    ],
                    "1.1.0": [],
                    "1.2.0": [{"yanked": True, "upload_time_iso_8601": "2026-02-01T00:00:00Z"}],
                }
            }
        }
    )
    facts = {p.version: p for p in live(FakeClient({}), index).pypi()}
    assert sorted(facts) == ["1.0.0", "1.2.0"]
    assert facts["1.0.0"].first_upload == datetime(2026, 1, 1, tzinfo=UTC)
    assert facts["1.2.0"].yanked and not facts["1.0.0"].yanked


def test_live_changelog_versions_come_from_the_requested_ref() -> None:
    body = "# Changelog\n## [0.2.0](x) (d)\n## [0.1.0] - d\n### [9.9.9] not a release heading\n"
    github = FakeClient({"/repos/acme/pkg/contents/CHANGELOG.md?ref=main": body})
    assert live(github).changelog_versions() == frozenset({"0.2.0", "0.1.0"})
    with pytest.raises(ra.AuditError):
        live(FakeClient({})).changelog_versions("abc")


# ------------------------------------------------------------ HTTP client behaviour


class FakeResponse:
    def __init__(self, status: int, body: str, headers: dict[str, str]) -> None:
        self.status = status
        self._body = body
        self._headers = headers

    def read(self) -> bytes:
        return self._body.encode()

    def getheader(self, name: str) -> str | None:
        return self._headers.get(name)


def patch_http(
    monkeypatch: pytest.MonkeyPatch,
    status: int = 200,
    body: str = "{}",
    headers: dict[str, str] | None = None,
    fail: bool = False,
) -> list[tuple[str, str, dict[str, str]]]:
    calls: list[tuple[str, str, dict[str, str]]] = []

    class FakeConnection:
        def __init__(self, host: str, timeout: int) -> None:
            self.host = host
            assert timeout == 30

        def request(self, method: str, path: str, headers: dict[str, str]) -> None:
            if fail:
                raise OSError("network down")
            calls.append((self.host, path, headers))

        def getresponse(self) -> FakeResponse:
            return FakeResponse(status, body, headers or {})

        def close(self) -> None:
            return None

    monkeypatch.setattr(http.client, "HTTPSConnection", FakeConnection)
    return calls


def test_client_sends_the_token_and_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_http(monkeypatch, body='{"a": 1}')
    assert ra.Client("api.github.com", "secret-value").json("/x") == {"a": 1}
    assert calls[0][2]["Authorization"] == "Bearer secret-value"
    calls = patch_http(monkeypatch)
    ra.Client("pypi.org").json("/y")
    assert "Authorization" not in calls[0][2]


def test_client_maps_failures_to_audit_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_http(monkeypatch, status=404)
    assert ra.Client("h").json("/x", optional=True) is None
    assert ra.Client("h").text("/x") is None
    with pytest.raises(ra.AuditError, match="HTTP 404"):
        ra.Client("h").json("/x")
    patch_http(monkeypatch, status=422)  # GitHub's answer for a ref that does not exist
    assert ra.Client("h").json("/x", optional=True) is None
    with pytest.raises(ra.AuditError, match="HTTP 422"):
        ra.Client("h").json("/x")
    patch_http(monkeypatch, status=500)
    with pytest.raises(ra.AuditError, match="HTTP 500"):
        ra.Client("h").text("/x")
    patch_http(monkeypatch, status=403, headers={"x-ratelimit-remaining": "0"})
    with pytest.raises(ra.AuditError, match="GH_TOKEN"):
        ra.Client("h").json("/x")
    patch_http(monkeypatch, body="<html>")
    with pytest.raises(ra.AuditError, match="not JSON"):
        ra.Client("h").json("/x")
    patch_http(monkeypatch, fail=True)
    with pytest.raises(ra.AuditError, match="network down"):
        ra.Client("h").json("/x")


def test_client_pages_follow_full_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {1: json.dumps(list(range(100))), 2: json.dumps([100])}
    served: list[str] = []

    class Paged(ra.Client):
        def get(self, path: str, accept: str = ra.JSON_ACCEPT) -> tuple[int, str]:
            served.append(path)
            return 200, pages[int(path.rsplit("=", 1)[1])]

    assert Paged("h").pages("/items") == [*range(100), 100]
    assert served == ["/items?per_page=100&page=1", "/items?per_page=100&page=2"]
