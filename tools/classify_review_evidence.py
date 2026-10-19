"""Classify GitHub PR review/comment records against the review-evidence
policy (#803, see docs/review-evidence-policy.md).

Advisory-only helper: given a review or inline-comment record shaped like
the GitHub REST API response, classify whether it counts as independent
review evidence for a given head commit, or is one of the documented
provenance pitfalls (author reply, stale commit, remapped inline comment).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CCR_OPEN_FINDINGS_MARKER = "<!-- ccr-overview-v2 -->"
_CHANGES_RECOMMENDED_TEXT = "Changes recommended"


@dataclass(frozen=True, slots=True)
class ReviewEvidence:
    reviewer: str
    reviewed_commit: str
    is_independent: bool
    reason: str


def classify_review(
    review: dict[str, Any], *, pr_author: str, current_head_sha: str
) -> ReviewEvidence:
    """Classify a formal PR review (``GET /pulls/{n}/reviews`` entry)."""
    reviewer = review.get("user", {}).get("login", "<unknown>")
    commit = review.get("commit_id", "")
    if reviewer == pr_author:
        return ReviewEvidence(reviewer, commit, False, "author-authored review is not independent")
    if commit != current_head_sha:
        return ReviewEvidence(
            reviewer, commit, False, "reviewed commit is stale relative to the current head"
        )
    return ReviewEvidence(reviewer, commit, True, "independent review of the current head")


def classify_inline_comment(
    comment: dict[str, Any], *, pr_author: str, current_head_sha: str
) -> ReviewEvidence:
    """Classify an inline PR comment (``GET /pulls/{n}/comments`` entry).

    Uses ``original_commit_id`` rather than ``commit_id``: GitHub re-targets
    an inline comment's ``commit_id`` to the latest push even when the
    comment was left against an earlier commit, so ``commit_id`` alone
    cannot be trusted as evidence of re-review (#803).
    """
    reviewer = comment.get("user", {}).get("login", "<unknown>")
    original_commit = comment.get("original_commit_id") or comment.get("commit_id", "")
    if comment.get("in_reply_to_id") is not None:
        return ReviewEvidence(
            reviewer,
            original_commit,
            False,
            "reply to an existing review thread, not a new independent review",
        )
    if reviewer == pr_author:
        return ReviewEvidence(
            reviewer, original_commit, False, "author-authored comment is not independent"
        )
    if original_commit != current_head_sha:
        return ReviewEvidence(
            reviewer,
            original_commit,
            False,
            "comment predates the current head; current commit_id may be remapped",
        )
    return ReviewEvidence(
        reviewer, original_commit, True, "independent comment on the current head"
    )


def has_open_findings(review_body: str) -> bool:
    """Return True for a Copilot review summary reporting open findings."""
    return CCR_OPEN_FINDINGS_MARKER in review_body and _CHANGES_RECOMMENDED_TEXT in review_body
