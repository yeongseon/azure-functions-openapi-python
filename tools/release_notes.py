#!/usr/bin/env python3
"""Standardize GitHub Release notes and credit human contributors.

Release Please stays the owner of versions, tags, ``CHANGELOG.md`` and the
GitHub Release it creates. This tool only *rewrites the body of an existing
GitHub Release* into one stable layout and adds verified attribution. It never
creates or moves tags, never touches ``CHANGELOG.md`` and never republishes
anything.

Layout (empty sections are omitted)::

    ## vX.Y.Z (YYYY-MM-DD)
    Notes            (status annotations, e.g. "not published to PyPI")
    Highlights
    Breaking Changes (+ upgrade notes)
    Features / Bug Fixes / Performance / Reverts
    New Contributors (only when independently verified)
    <details> Documentation, maintenance and other changes </details>
    **Full Changelog**: compare link

Rules that keep the notes honest:

* Items are *preserved*, not invented. The source is the existing release body
  (Release Please, GitHub-generated or hand-written). Only a release whose body
  is compare-link-only is reconstructed from the commits in its compare range,
  and it says so.
* ``by @user`` is reserved for external human contributors, drawn from the
  GitHub API, or from a ``Co-authored-by`` trailer whose address is a GitHub
  ``<id>+<login>@users.noreply.github.com`` address. Bots and logins listed in
  ``non_human_logins`` are never credited; nothing is guessed.
* "New Contributors" excludes the owner and lists an external human only when GitHub shows no earlier commit or
  merged PR by that login before the previous release.
* ``apply`` refuses to write when the new body drops a PR/commit reference the
  old body had, or loses a ``protected`` phrase from the config.

Stdlib-only on purpose, like the other release-gate tools. Network access goes
through the REST API (``GH_TOKEN`` in CI) behind the small ``GitHub`` protocol so
the logic is unit-testable with a fake.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import difflib
import http.client
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Protocol
from urllib.parse import quote

MARKER = "<!-- release-notes-format: v1 -->"
CONFIG_PATH = Path(".github/release-notes.json")

SECTION_ORDER = ("Breaking Changes", "Features", "Bug Fixes", "Performance", "Reverts")
OTHER = "Other changes"
CONVENTIONAL_SECTION = {
    "feat": "Features",
    "fix": "Bug Fixes",
    "perf": "Performance",
    "revert": "Reverts",
}
SECTION_EMOJI = {
    "Breaking Changes": "\u26a0\ufe0f ",
    "Features": "",
    "Bug Fixes": "",
    "Performance": "",
    "Reverts": "",
}

_PLUMBING_SUBJECT = re.compile(
    r"^(chore\(main\): release|(chore|docs|build)(\([^)]*\))?: (update changelog|bump version)|"
    r"bump version to|merge (pull request|branch))",
    re.IGNORECASE,
)
_CONVENTIONAL = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s+(?P<desc>.+)$"
)
_RP_SCOPE = re.compile(r"^\*\*(?P<scope>[^*]+):\*\*\s+(?P<desc>.+)$")
_GH_AUTO_TAIL = re.compile(
    r"\s+by @(?P<who>[\w\-\[\]]+) in https?://github\.com/[^\s]+/pull/(?P<pr>\d+)\s*$"
)
_LINK_PR = re.compile(r"\s*\(\[#(?P<pr>\d+)\]\([^)]*\)\)")
_LINK_SHA = re.compile(r"\s*\(\[(?P<sha>[0-9a-f]{7,40})\]\([^)]*\)\)")
_PLAIN_PR = re.compile(r"\s*\(#(?P<pr>\d+)\)")
_FULL_CHANGELOG = re.compile(r"^\*{0,2}Full Changelog\*{0,2}:.*$", re.IGNORECASE)
_NOREPLY = re.compile(r"(?:\d+\+)?(?P<login>[A-Za-z0-9\-]+)@users\.noreply\.github\.com$")
_TRAILER = re.compile(r"^Co-authored-by:\s*.*<(?P<email>[^>]+)>\s*$", re.IGNORECASE | re.MULTILINE)
_OUR_TAIL = re.compile(r"\s+by (?:@[\w\-\[\]]+)(?:, @[\w\-\[\]]+)*\s*$")
_HEADING = re.compile(r"^(?P<hashes>#{2,4})\s+(?P<text>.+?)\s*$")


# --------------------------------------------------------------------------- model


@dataclass
class Item:
    title: str
    section: str = OTHER
    prs: list[int] = field(default_factory=list)
    shas: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    key: str = ""

    def line(self) -> str:
        refs = [f"#{n}" for n in self.prs] or [f"`{s[:7]}`" for s in self.shas[:1]]
        text = self.title + (f" ({', '.join(refs)})" if refs else "")
        if self.authors:
            text += " by " + ", ".join(f"@{a}" for a in self.authors)
        return "\n".join([f"- {text}", *self.extra])


@dataclass
class Parsed:
    date: str | None = None
    notes: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    upgrade: list[str] = field(default_factory=list)
    upgrade_title: str = ""
    items: list[Item] = field(default_factory=list)
    compare_prev: str | None = None
    legacy_new_contributors: bool = False


@dataclass
class Commit:
    sha: str
    subject: str
    message: str
    login: str | None
    login_is_bot: bool = False


class GitHubError(RuntimeError):
    """A GitHub API request failed."""


class GitHub(Protocol):
    def releases(self) -> list[tuple[str, str]]: ...

    def release_body(self, tag: str) -> str: ...

    def compare(self, base: str, head: str) -> list[Commit]: ...

    def pr_authors(self) -> dict[int, tuple[str, bool]]: ...

    def had_prior_contribution(self, login: str, before_tag: str) -> bool: ...

    def set_body(self, tag: str, body: str) -> None: ...


@dataclass
class Config:
    repo: str
    owner_login: str | None = None
    legacy_repos: list[str] = field(default_factory=list)
    non_human_logins: set[str] = field(default_factory=set)
    protected: dict[str, list[str]] = field(default_factory=dict)
    # Evidence-backed clarifications per tag: {tag: {"notes"|"highlights"|"upgrade": [lines]}}
    annotations: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> Config:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            repo=data["repo"],
            owner_login=data.get("owner_login"),
            legacy_repos=list(data.get("legacy_repos", [])),
            non_human_logins={x.lower() for x in data.get("non_human_logins", [])},
            protected={k: list(v) for k, v in data.get("protected", {}).items()},
            annotations={
                tag: {block: list(lines) for block, lines in blocks.items()}
                for tag, blocks in data.get("annotations", {}).items()
            },
        )


# --------------------------------------------------------------------------- parsing


def _normalize_heading(text: str) -> str:
    return re.sub(r"[^a-z' ]+", "", text.lower()).strip()


def _classify_heading(text: str) -> tuple[str, str | None]:
    """Return (mode, section). Modes: highlights/notes/upgrade/skip/items."""
    h = _normalize_heading(text)
    if "highlight" in h:
        return "highlights", None
    if "new contributor" in h:
        return "skip", None
    if "upgrad" in h or "migrat" in h:
        return "upgrade", None
    if (
        h in {"notes", "note", "status", "release status"}
        or h.endswith(" notes")
        and "release" not in h
    ):
        return "notes", None
    if "break" in h:
        return "items", "Breaking Changes"
    if any(k in h for k in ("feature", "added", "enhancement")) or h == "new":
        return "items", "Features"
    if "fix" in h or "bug" in h:
        return "items", "Bug Fixes"
    if "perf" in h:
        return "items", "Performance"
    if "revert" in h:
        return "items", "Reverts"
    if "doc" in h:
        return "items", "Documentation"
    return "items", None


def _clean_title(raw: str) -> tuple[str, str | None, bool]:
    """Return (display title, conventional type, breaking-bang)."""
    scope_match = _RP_SCOPE.match(raw)
    if scope_match:
        return f"**{scope_match['scope']}:** {scope_match['desc']}", None, False
    conv = _CONVENTIONAL.match(raw)
    if conv and conv["type"] in {
        "feat", "fix", "perf", "revert", "docs", "refactor", "style", "test", "ci",
        "chore", "build",
    }:  # fmt: skip
        title = f"**{conv['scope']}:** {conv['desc']}" if conv["scope"] else conv["desc"]
        return title, conv["type"], bool(conv["bang"])
    return raw, None, False


def parse_item(text: str, section: str | None) -> Item:
    prs: list[int] = []
    shas: list[str] = []
    text = _OUR_TAIL.sub("", text.strip())
    auto = _GH_AUTO_TAIL.search(text)
    if auto:
        prs.append(int(auto["pr"]))
        text = text[: auto.start()]
    prs.extend(int(m["pr"]) for m in _LINK_PR.finditer(text))
    shas.extend(m["sha"] for m in _LINK_SHA.finditer(text))
    text = _LINK_SHA.sub("", _LINK_PR.sub("", text))
    for match in _PLAIN_PR.finditer(text):
        prs.append(int(match["pr"]))
    text = _PLAIN_PR.sub("", text).strip()
    title, ctype, bang = _clean_title(text)
    key = re.sub(r"^\*\*[^*]+:\*\*\s+", "", title).strip().lower()
    resolved = section
    if bang:
        resolved = "Breaking Changes"
    elif resolved in (None, OTHER) and ctype:
        resolved = CONVENTIONAL_SECTION.get(ctype, OTHER)
    return Item(title=title, section=resolved or OTHER, prs=sorted(set(prs)), shas=shas, key=key)


def parse_body(body: str) -> Parsed:
    """Split an existing release body into verbatim blocks and structured items."""
    parsed = Parsed()
    body = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    mode, section = "items", None
    verbatim_level = 0
    last: Item | None = None
    for line in body.splitlines():
        stripped = line.rstrip()
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped.strip()):
            continue
        if stripped.strip().startswith(("<details", "</details")):
            mode, section, last = "items", None, None
            continue
        if _FULL_CHANGELOG.match(stripped.strip()):
            compare = re.search(r"compare/([^\s)]+?)\.\.\.", stripped)
            if compare:
                parsed.compare_prev = compare[1]
            continue
        heading = _HEADING.match(stripped)
        if heading:
            level = len(heading["hashes"])
            if mode in {"highlights", "notes", "upgrade"} and level > verbatim_level:
                target = getattr(parsed, mode)
                target.append(stripped)
                continue
            text = heading["text"]
            rp = re.match(
                r"^\[?v?(\d+\.\d+\.\d+[^\]\s)]*)\]?(?:\([^)]*\))?\s*(?:\((\d{4}-\d{2}-\d{2})\))?$",
                text,
            )
            if level == 2 and rp:
                parsed.date = rp[2]
                mode, section = "items", None
                last = None
                continue
            mode, section = _classify_heading(text)
            if mode == "upgrade" and not parsed.upgrade_title:
                parsed.upgrade_title = text
            verbatim_level = level
            last = None
            continue
        if not stripped.strip():
            if mode in {"highlights", "notes", "upgrade"}:
                getattr(parsed, mode).append("")
            continue
        if mode in {"highlights", "notes", "upgrade"}:
            getattr(parsed, mode).append(stripped)
            continue
        if mode == "skip":
            continue
        bullet = re.match(r"^[-*]\s+(?P<text>.+)$", stripped)
        if bullet:
            last = parse_item(bullet["text"], section)
            parsed.items.append(last)
        elif line.startswith((" ", "\t")) and last is not None:
            last.extra.append(stripped)
        else:
            parsed.notes.append(stripped)
    for block in (parsed.notes, parsed.highlights, parsed.upgrade):
        while block and not block[-1].strip():
            block.pop()
        while block and not block[0].strip():
            block.pop(0)
    return parsed


# --------------------------------------------------------------------------- attribution


def _is_human(login: str | None, is_bot: bool, cfg: Config) -> bool:
    if not login or is_bot:
        return False
    low = login.lower()
    return not (low.endswith("[bot]") or low.startswith("app/") or low in cfg.non_human_logins)


def _is_external_human(login: str | None, is_bot: bool, cfg: Config) -> bool:
    """Credit verified humans other than this repository's owner."""
    return (
        login is not None
        and _is_human(login, is_bot, cfg)
        and (cfg.owner_login is None or login.lower() != cfg.owner_login.lower())
    )


def coauthors(message: str, cfg: Config) -> list[str]:
    """Logins from ``Co-authored-by`` trailers with a GitHub noreply address."""
    found: list[str] = []
    for match in _TRAILER.finditer(message):
        noreply = _NOREPLY.match(match["email"])
        if noreply and _is_human(noreply["login"], False, cfg):
            found.append(noreply["login"])
    return found


def _commit_key(subject: str) -> str:
    conv = _CONVENTIONAL.match(subject)
    return (conv["desc"] if conv else subject).strip().lower()


def attribute(
    item: Item,
    commits: list[Commit],
    pr_authors: dict[int, tuple[str, bool]],
    cfg: Config,
) -> None:
    people: list[str] = []

    def add(login: str | None, is_bot: bool = False) -> None:
        if login and _is_external_human(login, is_bot, cfg) and login not in people:
            people.append(login)

    for pr in item.prs:
        known = pr_authors.get(pr)
        if known:
            add(*known)
    matched = [
        c
        for c in commits
        if any(c.sha.startswith(s) for s in item.shas)
        or any(re.search(rf"\(#{pr}\)\s*$", c.subject) for pr in item.prs)
    ]
    if not item.prs and not item.shas and item.key:
        matched += [c for c in commits if _commit_key(c.subject) == item.key]
    for commit in matched[:1]:
        if not item.prs or not people:
            add(commit.login, commit.login_is_bot)
        for login in coauthors(commit.message, cfg):
            add(login)
    item.authors = people


def new_contributors(
    commits: list[Commit],
    gh: GitHub,
    prev_tag: str | None,
    cfg: Config,
    pr_authors: dict[int, tuple[str, bool]] | None = None,
) -> list[tuple[str, str]]:
    """External humans whose first merged contribution is in this range.

    ``commits`` come from the compare API in chronological order, so the first
    commit seen per login is the earliest. A login is celebrated only when GitHub
    shows no commit or merged PR by it before ``prev_tag``. Returns
    ``(login, reference)`` where the reference is ``#PR`` or a short SHA.
    """
    if prev_tag is None:
        return []
    first_seen: dict[str, str] = {}
    for commit in commits:
        if _PLUMBING_SUBJECT.match(commit.subject):
            continue
        pr = re.search(r"\(#(\d+)\)\s*$", commit.subject)
        ref = f"#{pr[1]}" if pr else commit.sha[:7]
        people: list[str] = []
        if pr and pr_authors:
            known = pr_authors.get(int(pr[1]))
            if known and _is_external_human(known[0], known[1], cfg):
                people.append(known[0])
        if commit.login and _is_external_human(commit.login, commit.login_is_bot, cfg):
            people.append(commit.login)
        people += [
            login
            for login in coauthors(commit.message, cfg)
            if _is_external_human(login, False, cfg)
        ]
        for login in people:
            if login:
                first_seen.setdefault(login, ref)
    return [
        (login, ref)
        for login, ref in first_seen.items()
        if not gh.had_prior_contribution(login, prev_tag)
    ]


# --------------------------------------------------------------------------- rendering


def render(
    tag: str,
    parsed: Parsed,
    cfg: Config,
    prev_tag: str | None,
    firsts: list[tuple[str, str]],
    reconstructed_from: str | None = None,
) -> str:
    def canon(text: str) -> str:
        for old in cfg.legacy_repos:
            text = text.replace(f"github.com/{old}/", f"github.com/{cfg.repo}/")
        return text

    out: list[str] = [f"## {tag}" + (f" ({parsed.date})" if parsed.date else ""), ""]
    notes = list(parsed.notes)
    if reconstructed_from:
        notes.append(
            f"_The original release text contained only a compare link. This summary was "
            f"reconstructed from the commits in `{reconstructed_from}`._"
        )
    if notes:
        out += ["### Notes", "", *map(canon, notes), ""]
    if parsed.highlights:
        out += ["### Highlights", "", *map(canon, parsed.highlights), ""]
    by_section: dict[str, list[Item]] = {}
    for item in parsed.items:
        by_section.setdefault(item.section, []).append(item)
    for name in SECTION_ORDER:
        section_items = by_section.pop(name, [])
        if name == "Breaking Changes" and (section_items or parsed.upgrade):
            out += [f"### {SECTION_EMOJI[name]}{name}", ""]
            out += [i.line() for i in section_items]
            if parsed.upgrade:
                title = parsed.upgrade_title or "Upgrade notes"
                out += ["", f"#### {title}", "", *map(canon, parsed.upgrade)]
            out.append("")
        elif section_items:
            out += [f"### {name}", "", *(i.line() for i in section_items), ""]
    if firsts:
        out += ["### New Contributors", ""]
        for login, ref in firsts:
            out.append(f"- @{login} made their first contribution in {ref}")
        out.append("")
    rest = [i for name, group in by_section.items() for i in group]
    classified = any(
        by_section_name in SECTION_ORDER for by_section_name in (i.section for i in parsed.items)
    )
    if rest and not classified:
        out += ["### Changes", "", *(i.line() for i in rest), ""]
    elif rest:
        out += [
            f"<details><summary>Documentation, maintenance and other changes ({len(rest)})"
            "</summary>",
            "",
            *(i.line() for i in rest),
            "",
            "</details>",
            "",
        ]
    if not parsed.items and not (parsed.highlights or notes or parsed.upgrade):
        out += [
            "_No user-facing changes could be reconstructed from the release history; "
            "see the full changelog for the exact commits._",
            "",
        ]
    if prev_tag:
        out.append(f"**Full Changelog**: https://github.com/{cfg.repo}/compare/{prev_tag}...{tag}")
    out += ["", MARKER]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).rstrip() + "\n"


# --------------------------------------------------------------------------- orchestration


def _version_key(tag: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", tag))


def previous_tag(
    tag: str, releases: list[tuple[str, str]], parsed: Parsed | None = None
) -> str | None:
    ordered = sorted((t for t, _ in releases), key=_version_key)
    if tag in ordered and ordered.index(tag) > 0:
        return ordered[ordered.index(tag) - 1]
    return parsed.compare_prev if parsed else None


def _commit_items(commits: list[Commit]) -> list[Item]:
    items: list[Item] = []
    for commit in commits:
        if _PLUMBING_SUBJECT.match(commit.subject):
            continue
        subject = re.sub(r"\s*\(#\d+\)\s*$", "", commit.subject)
        pr = re.search(r"\(#(\d+)\)\s*$", commit.subject)
        item = parse_item(subject, None)
        item.shas = [commit.sha]
        item.prs = [int(pr[1])] if pr else []
        items.append(item)
    return items


def apply_annotations(parsed: Parsed, blocks: dict[str, list[str]]) -> None:
    """Append maintainer-supplied clarifications once (re-rendering never duplicates)."""
    for name in ("notes", "highlights", "upgrade"):
        lines = blocks.get(name, [])
        target: list[str] = getattr(parsed, name)
        if lines and not any(lines[0] in existing for existing in target):
            target.extend(["", *lines] if target else lines)


def build_notes(
    tag: str,
    original: str,
    gh: GitHub,
    cfg: Config,
    published: str | None = None,
) -> str:
    releases = gh.releases()
    parsed = parse_body(original)
    prev = previous_tag(tag, releases, parsed)
    if parsed.date is None and published:
        parsed.date = published[:10]
    commits = gh.compare(prev, tag) if prev else []
    reconstructed = None
    if not parsed.items and not (parsed.highlights or parsed.notes or parsed.upgrade) and commits:
        parsed.items = _commit_items(commits)
        reconstructed = f"{prev}...{tag}"
    apply_annotations(parsed, cfg.annotations.get(tag, {}))
    pr_authors = gh.pr_authors()
    for item in parsed.items:
        attribute(item, commits, pr_authors, cfg)
    firsts = new_contributors(commits, gh, prev, cfg, pr_authors)
    body = render(tag, parsed, cfg, prev, firsts, reconstructed)
    problems = verify(original, body, tag, cfg)
    if problems:
        raise ValueError(f"{tag}: refusing to produce notes: " + "; ".join(problems))
    return body


def verify(original: str, new: str, tag: str, cfg: Config) -> list[str]:
    problems: list[str] = []
    stripped = re.sub(r"<!--.*?-->", "", original, flags=re.DOTALL)
    # Unverified "New Contributors" claims are intentionally replaced, not preserved.
    stripped = re.sub(
        r"^#{2,4}[^\n]*New Contributors[^\n]*\n(?:(?!#{2,4} |\*{0,2}Full Changelog).*\n?)*",
        "",
        stripped,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    refs = {m[1] or m[2] for m in re.finditer(r"/(?:pull|issues)/(\d+)|\[?\(?#(\d+)\b", stripped)}
    for pr in sorted(refs):
        if f"#{pr}" not in new:
            problems.append(f"lost PR reference #{pr}")
    for line in stripped.splitlines():
        if re.search(r"#\d+|/(?:pull|issues)/\d+", line):
            continue
        for sha in re.findall(r"\(\[([0-9a-f]{7,40})\]", line):
            if sha[:7] not in new:
                problems.append(f"lost commit reference {sha[:7]}")
    for phrase in cfg.protected.get(tag, []):
        if phrase not in new:
            problems.append(f"protected phrase missing: {phrase!r}")
    return sorted(set(problems))


# --------------------------------------------------------------------------- gh client


class GitHubApi:
    """GitHub REST API implementation of :class:`GitHub` (token from the environment).

    Uses ``http.client`` and an explicit ``GH_TOKEN``/``GITHUB_TOKEN`` instead of
    spawning the ``gh`` CLI, so the tool needs no subprocess. Locally:
    ``GH_TOKEN=$(gh auth token) python3 -m tools.release_notes ...``.
    """

    HOST = "api.github.com"

    def __init__(self, repo: str) -> None:
        self.repo = repo
        self._token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
        self._prs: dict[int, tuple[str, bool]] | None = None
        self._cache: dict[str, Any] = {}
        self._veterans: set[str] = set()
        self._release_cache: list[dict[str, Any]] | None = None

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "release-notes-tool",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        body = json.dumps(payload) if payload is not None else None
        conn = http.client.HTTPSConnection(self.HOST, timeout=30)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read().decode("utf-8")
        finally:
            conn.close()
        if response.status >= 400:
            raise GitHubError(f"{method} {path} -> HTTP {response.status}")
        return json.loads(raw) if raw else None

    def _get(self, path: str) -> Any:
        if path not in self._cache:
            self._cache[path] = self._request("GET", path)
        return self._cache[path]

    def _pages(self, path: str) -> list[Any]:
        joiner = "&" if "?" in path else "?"
        items: list[Any] = []
        page = 1
        while True:
            batch = self._request("GET", f"{path}{joiner}per_page=100&page={page}")
            items.extend(batch)
            if len(batch) < 100:
                return items
            page += 1

    def _all_releases(self) -> list[dict[str, Any]]:
        if self._release_cache is None:
            self._release_cache = self._pages(f"/repos/{self.repo}/releases")
        return self._release_cache

    def releases(self) -> list[tuple[str, str]]:
        return [
            (r["tag_name"], r["published_at"] or r["created_at"])
            for r in self._all_releases()
            if not r["draft"]
        ]

    def release_body(self, tag: str) -> str:
        for release in self._all_releases():
            if release["tag_name"] == tag:
                return str(release["body"] or "")
        raise GitHubError(f"no release for {tag}")

    def compare(self, base: str, head: str) -> list[Commit]:
        commits: list[Commit] = []
        page = 1
        while True:
            data = self._get(f"/repos/{self.repo}/compare/{base}...{head}?per_page=100&page={page}")
            batch = data.get("commits", [])
            for raw in batch:
                msg = raw["commit"]["message"]
                author = raw.get("author") or {}
                commits.append(
                    Commit(
                        sha=raw["sha"],
                        subject=msg.splitlines()[0] if msg else "",
                        message=msg,
                        login=author.get("login"),
                        login_is_bot=author.get("type") == "Bot",
                    )
                )
            if len(batch) < 100:
                return commits
            page += 1

    def pr_authors(self) -> dict[int, tuple[str, bool]]:
        if self._prs is None:
            self._prs = {
                p["number"]: (p["user"]["login"], p["user"].get("type") == "Bot")
                for p in self._pages(f"/repos/{self.repo}/pulls?state=closed")
                if p.get("merged_at") and p.get("user")
            }
        return self._prs

    def had_prior_contribution(self, login: str, before_tag: str) -> bool:
        """True when GitHub shows an earlier contribution, or when it cannot tell.

        Failing closed means an unverifiable login is never celebrated as new.
        """
        if login in self._veterans:
            return True  # an earlier contribution is also earlier than any later tag
        try:
            ref = self._get(f"/repos/{self.repo}/commits/{before_tag}")
            before = ref["commit"]["committer"]["date"]
            found = bool(
                self._get(
                    f"/repos/{self.repo}/commits?author={quote(login)}&until={before}&per_page=1"
                )
            )
            if not found:
                query = quote(f"repo:{self.repo} is:pr is:merged author:{login} merged:<{before}")
                result = self._get(f"/search/issues?q={query}")
                found = int(result.get("total_count", 0)) > 0
        except (GitHubError, KeyError, ValueError, OSError):
            return True
        if found:
            self._veterans.add(login)
        return found

    def set_body(self, tag: str, body: str) -> None:
        release = self._request("GET", f"/repos/{self.repo}/releases/tags/{quote(tag)}")
        self._request("PATCH", f"/repos/{self.repo}/releases/{release['id']}", {"body": body})


# --------------------------------------------------------------------------- CLI


def _backup_tags(directory: Path) -> list[Path]:
    return sorted((p for p in directory.glob("v*.json")), key=lambda p: _version_key(p.stem))


def cmd_preview(args: argparse.Namespace, cfg: Config, gh: GitHub) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    failures = 0
    summary: list[str] = []
    for path in _backup_tags(Path(args.backup)):
        data = json.loads(path.read_text(encoding="utf-8"))
        tag = data["tagName"]
        old = data["body"] or ""
        try:
            new = build_notes(tag, old, gh, cfg, data.get("publishedAt"))
        except ValueError as err:
            failures += 1
            summary.append(f"FAIL {tag}: {err}")
            continue
        (out / f"{tag}.md").write_text(new, encoding="utf-8")
        diff = "".join(
            difflib.unified_diff(
                old.splitlines(True), new.splitlines(True), f"{tag} (current)", f"{tag} (new)"
            )
        )
        (out / f"{tag}.diff").write_text(diff, encoding="utf-8")
        credited = sorted(
            {a for m in re.findall(r"by (@[\w\-]+(?:, @[\w\-]+)*)", new) for a in m.split(", ")}
        )
        summary.append(
            f"ok   {tag}: {len(old)} -> {len(new)} chars; credits: {', '.join(credited) or '-'}"
        )
    (out / "SUMMARY.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary))
    return 1 if failures else 0


def cmd_render(args: argparse.Namespace, cfg: Config, gh: GitHub) -> int:
    published = dict(gh.releases()).get(args.tag)
    original = (
        Path(args.body_file).read_text(encoding="utf-8")
        if args.body_file
        else gh.release_body(args.tag)
    )
    sys.stdout.write(build_notes(args.tag, original, gh, cfg, published))
    return 0


def cmd_apply(args: argparse.Namespace, cfg: Config, gh: GitHub) -> int:
    original = gh.release_body(args.tag)
    if MARKER in original and not args.force:
        print(f"{args.tag}: already standardized; nothing to do")
        return 0
    published = dict(gh.releases()).get(args.tag)
    new = build_notes(args.tag, original, gh, cfg, published)
    if args.dry_run:
        sys.stdout.write(new)
        return 0
    if args.backup:
        directory = Path(args.backup)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{args.tag}.json").write_text(
            json.dumps({"tagName": args.tag, "body": original}, indent=2), encoding="utf-8"
        )
    gh.set_body(args.tag, new)
    print(f"{args.tag}: release notes updated")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    sub = parser.add_subparsers(dest="command", required=True)
    p_prev = sub.add_parser("preview", help="render every backed-up release into --out")
    p_prev.add_argument("--backup", required=True, help="dir of vX.Y.Z.json release dumps")
    p_prev.add_argument("--out", required=True)
    p_render = sub.add_parser("render", help="print standardized notes for one tag")
    p_render.add_argument("tag")
    p_render.add_argument("--body-file")
    p_apply = sub.add_parser("apply", help="rewrite one GitHub Release body (idempotent)")
    p_apply.add_argument("tag")
    p_apply.add_argument("--dry-run", action="store_true")
    p_apply.add_argument("--force", action="store_true", help="re-render even if already done")
    p_apply.add_argument("--backup", help="dir to save the previous body before editing")
    args = parser.parse_args(argv)
    cfg = Config.load(Path(args.config))
    gh = GitHubApi(cfg.repo)
    handler = {"preview": cmd_preview, "render": cmd_render, "apply": cmd_apply}[args.command]
    return handler(args, cfg, gh)


if __name__ == "__main__":
    raise SystemExit(main())
