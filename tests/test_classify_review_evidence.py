"""Fixtures-based regression tests for tools/classify_review_evidence.py
(#803, see docs/review-evidence-policy.md).

Fixtures are synthetic but shaped like the documented provenance patterns:
a final-head author-reply, a remapped inline-comment commit, and the
'<!-- ccr-overview-v2 -->' summary marker. No real PR data is scraped.
"""

from __future__ import annotations

from tools.classify_review_evidence import (
    classify_inline_comment,
    classify_review,
    has_open_findings,
)

PR_AUTHOR = "yeongseon"
CURRENT_HEAD = "cccccc2"


class TestClassifyReview:
    def test_independent_review_of_current_head_is_evidence(self) -> None:
        review = {"user": {"login": "copilot-pull-request-reviewer"}, "commit_id": CURRENT_HEAD}

        result = classify_review(review, pr_author=PR_AUTHOR, current_head_sha=CURRENT_HEAD)

        assert result.is_independent is True

    def test_review_of_stale_commit_is_not_evidence(self) -> None:
        """A review of an earlier commit is not evidence for a later head --
        a push after review invalidates it."""
        review = {"user": {"login": "copilot-pull-request-reviewer"}, "commit_id": "aaaaaa1"}

        result = classify_review(review, pr_author=PR_AUTHOR, current_head_sha=CURRENT_HEAD)

        assert result.is_independent is False
        assert "stale" in result.reason

    def test_author_authored_review_is_not_independent(self) -> None:
        review = {"user": {"login": PR_AUTHOR}, "commit_id": CURRENT_HEAD}

        result = classify_review(review, pr_author=PR_AUTHOR, current_head_sha=CURRENT_HEAD)

        assert result.is_independent is False
        assert "author" in result.reason

    def test_missing_reviewer_login_falls_back_to_unknown(self) -> None:
        review = {"user": {}, "commit_id": CURRENT_HEAD}

        result = classify_review(review, pr_author=PR_AUTHOR, current_head_sha=CURRENT_HEAD)

        assert result.reviewer == "<unknown>"


class TestClassifyInlineComment:
    def test_final_head_author_reply_is_not_independent(self) -> None:
        """A PR author's reply to an existing thread on the final head is
        not a new independent review, even though it is the most recent
        activity on that commit."""
        comment = {
            "user": {"login": PR_AUTHOR},
            "original_commit_id": CURRENT_HEAD,
            "commit_id": CURRENT_HEAD,
            "in_reply_to_id": 4265395043,
        }

        result = classify_inline_comment(
            comment, pr_author=PR_AUTHOR, current_head_sha=CURRENT_HEAD
        )

        assert result.is_independent is False
        assert "reply" in result.reason

    def test_remapped_inline_comment_commit_is_not_evidence(self) -> None:
        """GitHub re-targets an inline comment's commit_id to the latest
        push even when original_commit_id still names an earlier commit --
        only original_commit_id is trustworthy provenance."""
        comment = {
            "user": {"login": "a-reviewer"},
            "original_commit_id": "bbbbbb1",
            "commit_id": CURRENT_HEAD,
        }

        result = classify_inline_comment(
            comment, pr_author=PR_AUTHOR, current_head_sha=CURRENT_HEAD
        )

        assert result.is_independent is False
        assert result.reviewed_commit == "bbbbbb1"
        assert "predates" in result.reason

    def test_independent_comment_on_current_head_is_evidence(self) -> None:
        comment = {
            "user": {"login": "a-reviewer"},
            "original_commit_id": CURRENT_HEAD,
            "commit_id": CURRENT_HEAD,
        }

        result = classify_inline_comment(
            comment, pr_author=PR_AUTHOR, current_head_sha=CURRENT_HEAD
        )

        assert result.is_independent is True


class TestHasOpenFindings:
    def test_detects_changes_recommended_summary(self) -> None:
        body = "<!-- ccr-overview-v2 -->\n## Changes recommended\n- fix X"

        assert has_open_findings(body) is True

    def test_no_marker_returns_false(self) -> None:
        assert has_open_findings("Looks good to me") is False

    def test_marker_without_changes_recommended_returns_false(self) -> None:
        body = "<!-- ccr-overview-v2 -->\nNo issues found."

        assert has_open_findings(body) is False
