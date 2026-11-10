#!/usr/bin/env python3
"""Read-only audit of release history across Git tags, GitHub Releases, CHANGELOG and PyPI.

Release Please owns versions, tags, ``CHANGELOG.md`` and the GitHub Release; ``publish-pypi.yml``
owns the PyPI upload. This tool owns none of that. It only *reads* those four records and
reports where they disagree, so a mismatch cannot hide behind a green GitHub Release.

Commands::

    audit             whole history; exit 1 on any discrepancy that is not an approved exception
    check-tag TAG     one new tag: version file, mainline ancestry and CHANGELOG section agree
    check-published   poll PyPI until TAG's version is downloadable (a GitHub Release is no proof)

Exit codes: 0 clean, 1 discrepancy found, 2 the audit itself could not run (it fails closed).

Known historical exceptions live in ``.github/release-audit.json`` and are explained in
``docs/release_history.md``. An exception must match the computed findings exactly, so one that
no longer applies (or no longer covers everything found) is reported instead of silently rotting.
Tags are never moved, deleted or created, and nothing is written anywhere.

Stdlib-only on purpose, like the other release-gate tools, and no subprocess: Git facts come from
the GitHub REST API (``GH_TOKEN`` or ``GITHUB_TOKEN``) behind the small ``Sources`` protocol so the
logic is unit-testable with a fake.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import http.client
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Protocol
from urllib.parse import quote

CONFIG_PATH = Path(".github/release-audit.json")

TAG_VERSION_MISMATCH = "TAG_VERSION_MISMATCH"
TAG_NOT_ON_MAINLINE = "TAG_NOT_ON_MAINLINE"
TAG_ONLY = "TAG_ONLY"
PYPI_WITHOUT_TAG = "PYPI_WITHOUT_TAG"
PYPI_WITHOUT_RELEASE = "PYPI_WITHOUT_RELEASE"
RELEASE_WITHOUT_PYPI = "RELEASE_WITHOUT_PYPI"
RELEASE_WITHOUT_TAG = "RELEASE_WITHOUT_TAG"
CHANGELOG_MISSING = "CHANGELOG_MISSING"

CODES = {
    TAG_VERSION_MISMATCH: "the tagged source declares a different version than the tag",
    TAG_NOT_ON_MAINLINE: "the tagged commit is not on the history of the mainline branch",
    TAG_ONLY: "a tag with neither a PyPI distribution nor a GitHub Release",
    PYPI_WITHOUT_TAG: "published to PyPI but no Git tag exists",
    PYPI_WITHOUT_RELEASE: "published to PyPI and tagged but no GitHub Release exists",
    RELEASE_WITHOUT_PYPI: "a GitHub Release exists but nothing was published to PyPI",
    RELEASE_WITHOUT_TAG: "a GitHub Release exists but its tag does not",
    CHANGELOG_MISSING: "tagged, released or published but the changelog has no section for it",
}
# A release that is still on its way through the publish gate is not yet a discrepancy.
PENDING_CODES = frozenset({TAG_ONLY, RELEASE_WITHOUT_PYPI})

RAW = "application/vnd.github.raw+json"
JSON_ACCEPT = "application/vnd.github+json"


class AuditError(RuntimeError):
    """The audit could not run (bad configuration, network failure, unexpected data)."""


# --------------------------------------------------------------------------- model


@dataclass(frozen=True)
class Approved:
    codes: frozenset[str]
    reason: str
    ref: str = ""


@dataclass(frozen=True)
class Config:
    repo: str
    package: str
    mainline: str = "main"
    tag_prefix: str = "v"
    version_files: tuple[str, ...] = ("src/azure_functions_openapi/__init__.py",)
    changelog: str = "CHANGELOG.md"
    grace_hours: float = 12.0
    approved: dict[str, Approved] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> Config:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise AuditError(f"cannot read {path}: {err}") from err
        if not isinstance(data, dict):
            raise AuditError(f"{path}: expected a JSON object")
        approved: dict[str, Approved] = {}
        for version, entry in dict(data.get("approved", {})).items():
            codes = frozenset(entry.get("codes", []))
            unknown = sorted(codes - CODES.keys())
            if unknown or not codes:
                raise AuditError(f"{path}: {version}: unknown or empty codes {unknown}")
            if not str(entry.get("reason", "")).strip():
                raise AuditError(f"{path}: {version}: an approved exception needs a reason")
            approved[version] = Approved(codes, str(entry["reason"]), str(entry.get("ref", "")))
        try:
            return cls(
                repo=str(data["repo"]),
                package=str(data["package"]),
                mainline=str(data.get("mainline", "main")),
                tag_prefix=str(data.get("tag_prefix", "v")),
                version_files=tuple(data.get("version_files", cls.version_files)),
                changelog=str(data.get("changelog", "CHANGELOG.md")),
                grace_hours=float(data.get("grace_hours", 12.0)),
                approved=approved,
            )
        except KeyError as err:
            raise AuditError(f"{path}: missing required key {err}") from err


@dataclass(frozen=True)
class TagFact:
    name: str
    commit: str
    committed_at: datetime
    declared_version: str | None
    on_mainline: bool


@dataclass(frozen=True)
class ReleaseFact:
    tag: str
    prerelease: bool
    published_at: datetime | None


@dataclass(frozen=True)
class PyPIFact:
    version: str
    yanked: bool
    first_upload: datetime


@dataclass(frozen=True)
class Facts:
    tags: dict[str, TagFact]
    releases: dict[str, ReleaseFact]
    pypi: dict[str, PyPIFact]
    changelog_versions: frozenset[str]


class Sources(Protocol):
    def tag_facts(self) -> list[TagFact]: ...

    def tag(self, name: str) -> TagFact | None: ...

    def releases(self) -> list[ReleaseFact]: ...

    def pypi(self) -> list[PyPIFact]: ...

    def changelog_versions(self, ref: str | None = None) -> frozenset[str]: ...


# --------------------------------------------------------------------------- classification


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def classify(version: str, facts: Facts) -> set[str]:
    """Every discrepancy for one version, before any exception or grace period is applied."""
    tag = facts.tags.get(version)
    release = facts.releases.get(version)
    published = facts.pypi.get(version)
    found: set[str] = set()
    if tag is not None:
        if tag.declared_version != version:
            found.add(TAG_VERSION_MISMATCH)
        if not tag.on_mainline:
            found.add(TAG_NOT_ON_MAINLINE)
        if release is None and published is None:
            found.add(TAG_ONLY)
        if published is not None and release is None:
            found.add(PYPI_WITHOUT_RELEASE)
        if release is not None and published is None:
            found.add(RELEASE_WITHOUT_PYPI)
    else:
        if release is not None:
            found.add(RELEASE_WITHOUT_TAG)
        if published is not None:
            found.add(PYPI_WITHOUT_TAG)
    if (tag or release or published) and version not in facts.changelog_versions:
        found.add(CHANGELOG_MISSING)
    return found


def _age(version: str, facts: Facts, now: datetime) -> timedelta | None:
    tag = facts.tags.get(version)
    release = facts.releases.get(version)
    stamps = [
        when
        for when in (tag.committed_at if tag else None, release.published_at if release else None)
        if when is not None
    ]
    return now - max(stamps) if stamps else None


@dataclass(frozen=True)
class Finding:
    version: str
    approved: tuple[str, ...] = ()
    unapproved: tuple[str, ...] = ()
    stale: tuple[str, ...] = ()
    pending: tuple[str, ...] = ()
    reason: str = ""
    ref: str = ""

    @property
    def failing(self) -> bool:
        return bool(self.unapproved or self.stale)


@dataclass(frozen=True)
class Report:
    repo: str
    package: str
    counts: dict[str, int]
    findings: tuple[Finding, ...]

    @property
    def ok(self) -> bool:
        return not any(f.failing for f in self.findings)


def audit(cfg: Config, facts: Facts, now: datetime, grace_hours: float | None = None) -> Report:
    grace = timedelta(hours=cfg.grace_hours if grace_hours is None else grace_hours)
    versions = set(facts.tags) | set(facts.releases) | set(facts.pypi) | set(cfg.approved)
    findings: list[Finding] = []
    for version in sorted(versions, key=version_key):
        found = classify(version, facts)
        age = _age(version, facts, now)
        pending = {c for c in found if c in PENDING_CODES and age is not None and age < grace}
        found -= pending
        allowed = cfg.approved.get(version)
        expected = set(allowed.codes) if allowed else set()
        unapproved = found - expected
        stale = expected - found
        covered = found & expected
        if not (unapproved or stale or covered or pending):
            continue
        findings.append(
            Finding(
                version=version,
                approved=tuple(sorted(covered)),
                unapproved=tuple(sorted(unapproved)),
                stale=tuple(sorted(stale)),
                pending=tuple(sorted(pending)),
                reason=allowed.reason if allowed else "",
                ref=allowed.ref if allowed else "",
            )
        )
    counts = {
        "tags": len(facts.tags),
        "github_releases": len(facts.releases),
        "pypi_versions": len(facts.pypi),
        "changelog_sections": len(facts.changelog_versions),
    }
    return Report(cfg.repo, cfg.package, counts, tuple(findings))


def collect(cfg: Config, sources: Sources) -> Facts:
    return Facts(
        tags={t.name.removeprefix(cfg.tag_prefix): t for t in sources.tag_facts()},
        releases={r.tag.removeprefix(cfg.tag_prefix): r for r in sources.releases()},
        pypi={p.version: p for p in sources.pypi()},
        changelog_versions=sources.changelog_versions(cfg.mainline),
    )


def render(report: Report, grace_hours: float) -> str:
    lines = [
        f"release audit: {report.repo} (PyPI package {report.package})",
        "checked: " + ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in report.counts.items()),
        "",
    ]
    sections: tuple[tuple[str, Callable[[Finding], tuple[str, ...]]], ...] = (
        ("UNAPPROVED discrepancies", lambda f: f.unapproved),
        ("STALE exceptions (no longer match; update the config)", lambda f: f.stale),
        (f"PENDING (younger than {grace_hours:g}h, may still be publishing)", lambda f: f.pending),
        ("APPROVED historical exceptions", lambda f: f.approved),
    )
    for title, pick in sections:
        rows = [(f, pick(f)) for f in report.findings if pick(f)]
        lines.append(f"{title}: {len(rows)}")
        for finding, codes in rows:
            lines.append(f"  {finding.version:<8} {', '.join(codes)}")
            for code in codes:
                lines.append(f"           - {CODES[code]}")
            if title.startswith("APPROVED") and finding.reason:
                lines.append(f"           reason: {finding.reason}")
        lines.append("")
    lines.append("RESULT: " + ("OK" if report.ok else "DISCREPANCIES FOUND"))
    return "\n".join(lines) + "\n"


def to_json(report: Report) -> str:
    return json.dumps(
        {
            "ok": report.ok,
            "repo": report.repo,
            "package": report.package,
            "counts": report.counts,
            "findings": [
                {
                    "version": f.version,
                    "approved": list(f.approved),
                    "unapproved": list(f.unapproved),
                    "stale": list(f.stale),
                    "pending": list(f.pending),
                    "reason": f.reason,
                    "ref": f.ref,
                }
                for f in report.findings
            ],
        },
        indent=2,
    )


# --------------------------------------------------------------------------- single-tag checks


def check_tag(
    name: str,
    cfg: Config,
    sources: Sources,
    wait_seconds: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> list[str]:
    """Problems that make ``name`` an unsafe release tag (empty list means it looks sound).

    ``wait_seconds`` only covers a tag that is not visible through the API yet; every other
    problem is deterministic and reported at once.
    """
    match = re.fullmatch(rf"{re.escape(cfg.tag_prefix)}(\d+\.\d+\.\d+)", name)
    if match is None:
        return [f"{name!r} is not a release tag ({cfg.tag_prefix}X.Y.Z)"]
    version = match[1]
    deadline = clock() + wait_seconds
    tag = sources.tag(name)
    while tag is None and clock() < deadline:
        sleep(min(5.0, deadline - clock()))
        tag = sources.tag(name)
    if tag is None:
        return [f"tag {name} does not exist"]
    problems: list[str] = []
    if tag.declared_version != version:
        problems.append(
            f"source at {tag.commit[:7]} declares version {tag.declared_version!r}, not {version!r}"
        )
    if not tag.on_mainline:
        problems.append(f"{tag.commit[:7]} is not on the history of {cfg.mainline}")
    if version not in sources.changelog_versions(tag.commit):
        problems.append(f"{cfg.changelog} has no section for {version} at {tag.commit[:7]}")
    return problems


def check_published(
    name: str,
    cfg: Config,
    sources: Sources,
    wait_minutes: float,
    interval_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """True once PyPI serves a non-yanked distribution of ``name``'s version."""
    version = name.removeprefix(cfg.tag_prefix)
    deadline = clock() + wait_minutes * 60
    while True:
        if any(p.version == version and not p.yanked for p in sources.pypi()):
            return True
        if clock() >= deadline:
            return False
        sleep(interval_seconds)


# --------------------------------------------------------------------------- live sources


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise AuditError(f"expected a timestamp, got {value!r}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise AuditError(f"bad timestamp {value!r}") from err
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _mapping(value: object, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuditError(f"unexpected response for {what}")
    return value


def _sequence(value: object, what: str) -> list[Any]:
    if not isinstance(value, list):
        raise AuditError(f"unexpected response for {what}")
    return value


class Client:
    """Minimal HTTPS JSON client with an explicit timeout and no redirects followed."""

    def __init__(self, host: str, token: str | None = None) -> None:
        self.host = host
        self._token = token or ""

    def get(self, path: str, accept: str = JSON_ACCEPT) -> tuple[int, str]:
        headers = {
            "Accept": accept,
            "User-Agent": "release-audit-tool",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        conn = http.client.HTTPSConnection(self.host, timeout=30)
        try:
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            body = response.read().decode("utf-8")
            status = response.status
            exhausted = response.getheader("x-ratelimit-remaining") == "0"
        except (OSError, http.client.HTTPException) as err:
            raise AuditError(f"GET {self.host}{path} failed: {err}") from err
        finally:
            conn.close()
        if status in (403, 429) and exhausted:
            raise AuditError(
                f"{self.host} rate limit exceeded; set GH_TOKEN or GITHUB_TOKEN to audit"
            )
        return status, body

    def json(self, path: str, optional: bool = False) -> Any:
        status, body = self.get(path)
        if status in (404, 422) and optional:
            return None
        if status >= 400:
            raise AuditError(f"GET {self.host}{path} -> HTTP {status}")
        try:
            return json.loads(body)
        except ValueError as err:
            raise AuditError(f"GET {self.host}{path}: response is not JSON") from err

    def text(self, path: str) -> str | None:
        status, body = self.get(path, RAW)
        if status == 404:
            return None
        if status >= 400:
            raise AuditError(f"GET {self.host}{path} -> HTTP {status}")
        return body

    def pages(self, path: str) -> list[Any]:
        joiner = "&" if "?" in path else "?"
        items: list[Any] = []
        page = 1
        while True:
            batch = _sequence(self.json(f"{path}{joiner}per_page=100&page={page}"), path)
            items.extend(batch)
            if len(batch) < 100:
                return items
            page += 1


class JsonClient(Protocol):
    def json(self, path: str, optional: bool = False) -> Any: ...

    def text(self, path: str) -> str | None: ...

    def pages(self, path: str) -> list[Any]: ...


class LiveSources:
    """GitHub REST API and PyPI JSON API implementation of :class:`Sources`."""

    def __init__(
        self,
        cfg: Config,
        token: str,
        github: JsonClient | None = None,
        pypi: JsonClient | None = None,
    ) -> None:
        self.cfg = cfg
        self._github: JsonClient = github if github is not None else Client("api.github.com", token)
        self._pypi: JsonClient = pypi if pypi is not None else Client("pypi.org")
        self._mainline: set[str] = set()
        self._mainline_page = 1
        self._mainline_done = False

    def _on_mainline(self, sha: str) -> bool:
        """Page through the mainline history lazily; a fresh tag is found on the first page."""
        while sha not in self._mainline and not self._mainline_done:
            path = (
                f"/repos/{self.cfg.repo}/commits?sha={quote(self.cfg.mainline, safe='')}"
                f"&per_page=100&page={self._mainline_page}"
            )
            batch = _sequence(self._github.json(path), path)
            self._mainline.update(str(_mapping(c, path)["sha"]) for c in batch)
            self._mainline_page += 1
            self._mainline_done = len(batch) < 100
        return sha in self._mainline

    def _declared_version(self, sha: str) -> str | None:
        for path in self.cfg.version_files:
            text = self._github.text(f"/repos/{self.cfg.repo}/contents/{quote(path)}?ref={sha}")
            if text is not None:
                found = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
                return found[1] if found else None
        return None

    def tag(self, name: str) -> TagFact | None:
        path = f"/repos/{self.cfg.repo}/commits/{quote(name, safe='')}"
        data = self._github.json(path, optional=True)
        if data is None:
            return None
        commit = _mapping(data, path)
        sha = str(commit["sha"])
        committed = _mapping(_mapping(commit["commit"], path)["committer"], path)["date"]
        return TagFact(
            name=name,
            commit=sha,
            committed_at=_parse_time(committed),
            declared_version=self._declared_version(sha),
            on_mainline=self._on_mainline(sha),
        )

    def tag_facts(self) -> list[TagFact]:
        prefix = quote(self.cfg.tag_prefix, safe="")
        refs = self._github.pages(f"/repos/{self.cfg.repo}/git/matching-refs/tags/{prefix}")
        pattern = re.compile(rf"refs/tags/({re.escape(self.cfg.tag_prefix)}\d+\.\d+\.\d+)")
        names = sorted(
            {m[1] for ref in refs if (m := pattern.fullmatch(str(_mapping(ref, "refs")["ref"])))},
            key=version_key,
        )
        facts = [self.tag(name) for name in names]
        return [fact for fact in facts if fact is not None]

    def releases(self) -> list[ReleaseFact]:
        raw = self._github.pages(f"/repos/{self.cfg.repo}/releases")
        out: list[ReleaseFact] = []
        for item in raw:
            release = _mapping(item, "releases")
            if release.get("draft"):
                continue
            published = release.get("published_at")
            out.append(
                ReleaseFact(
                    tag=str(release["tag_name"]),
                    prerelease=bool(release.get("prerelease")),
                    published_at=_parse_time(published) if published else None,
                )
            )
        return out

    def pypi(self) -> list[PyPIFact]:
        path = f"/pypi/{quote(self.cfg.package)}/json"
        data = _mapping(self._pypi.json(path), path)
        out: list[PyPIFact] = []
        for version, files in _mapping(data.get("releases", {}), path).items():
            uploads = _sequence(files, path)
            if not uploads:
                continue
            records = [_mapping(f, path) for f in uploads]
            out.append(
                PyPIFact(
                    version=version,
                    yanked=all(bool(f.get("yanked")) for f in records),
                    first_upload=min(_parse_time(f["upload_time_iso_8601"]) for f in records),
                )
            )
        return out

    def changelog_versions(self, ref: str | None = None) -> frozenset[str]:
        at = quote(ref or self.cfg.mainline, safe="")
        text = self._github.text(
            f"/repos/{self.cfg.repo}/contents/{quote(self.cfg.changelog)}?ref={at}"
        )
        if text is None:
            raise AuditError(f"{self.cfg.changelog} not found at {ref or self.cfg.mainline}")
        return frozenset(re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, re.MULTILINE))


# --------------------------------------------------------------------------- CLI


def main(
    argv: Sequence[str] | None = None,
    *,
    sources: Sources | None = None,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--config", default=str(CONFIG_PATH))
    sub = parser.add_subparsers(dest="command", required=True)
    p_audit = sub.add_parser("audit", help="audit the whole release history")
    p_audit.add_argument("--json", action="store_true", help="machine-readable output")
    p_audit.add_argument("--grace-hours", type=float, help="override the configured grace period")
    p_tag = sub.add_parser("check-tag", help="verify one new release tag before it is trusted")
    p_tag.add_argument("tag")
    p_tag.add_argument(
        "--wait-seconds", type=float, default=0.0, help="wait for a tag the API does not show yet"
    )
    p_pub = sub.add_parser("check-published", help="wait until PyPI serves the tag's version")
    p_pub.add_argument("tag")
    p_pub.add_argument("--wait-minutes", type=float, default=0.0)
    p_pub.add_argument("--interval-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    try:
        cfg = Config.load(Path(args.config))
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
        live = sources if sources is not None else LiveSources(cfg, token)
        if args.command == "audit":
            moment = now or datetime.now(UTC)
            grace = cfg.grace_hours if args.grace_hours is None else args.grace_hours
            report = audit(cfg, collect(cfg, live), moment, grace)
            sys.stdout.write(to_json(report) + "\n" if args.json else render(report, grace))
            return 0 if report.ok else 1
        if args.command == "check-tag":
            problems = check_tag(args.tag, cfg, live, args.wait_seconds, sleep)
            for problem in problems:
                print(f"{args.tag}: {problem}", file=sys.stderr)
            if not problems:
                print(f"{args.tag}: version, mainline history and changelog agree")
            return 1 if problems else 0
        published = check_published(
            args.tag, cfg, live, args.wait_minutes, args.interval_seconds, sleep
        )
        if published:
            print(f"{args.tag}: published on PyPI as {cfg.package}")
            return 0
        print(
            f"{args.tag}: {cfg.package} {args.tag.removeprefix(cfg.tag_prefix)} is not on PyPI; "
            "a GitHub Release is not proof of publication",
            file=sys.stderr,
        )
        return 1
    except AuditError as err:
        print(f"release audit could not run: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
