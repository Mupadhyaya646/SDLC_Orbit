"""
gh_create_pr — open a GitHub PR via the `gh` CLI (title/description/base/
reviewers), authenticated via GH_TOKEN (gh CLI's standard non-interactive
auth env var, set from this server's own GITHUB_TOKEN).
"""

from __future__ import annotations

import json
import logging
import re

from .base import GitOpsToolBase

logger = logging.getLogger(__name__)

_PR_URL_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/pull/(\d+)")


class GhCreatePrTool(GitOpsToolBase):
    """gh pr create with title/description/base/reviewers."""

    name = "gh_create_pr"
    description = "gh pr create with title/description/base/reviewers."

    @classmethod
    def execute(
        cls,
        title: str,
        body: str,
        base: str,
        head: str | None = None,
        reviewers: list[str] | None = None,
        branch: str | None = None,
    ) -> dict:
        """
        Args:
            title: PR title.
            body: PR description.
            base: target branch the PR merges into (e.g. "main").
            head: source branch (the feature branch with the commit). If
                omitted, uses whatever branch the persistent clone
                currently has checked out.
            reviewers: GitHub usernames (handles, not display names or
                emails — per the original design's explicit note).
            branch: branch to sync the clone to before running `gh` (gh
                CLI needs to run inside the repo's working tree to infer
                the remote).

        Returns:
            dict with success flag, pr_url, pr_number on success;
            success=False + error on failure.
        """
        if not title or not title.strip():
            return cls._format_error("title is required", error_type="ValidationError")
        if not base or not base.strip():
            return cls._format_error("base is required", error_type="ValidationError")

        try:
            repo = cls.ensure_repo_cloned_and_synced(branch=branch)
        except Exception as exc:
            return cls._format_error(f"Could not sync repo clone: {exc}", error_type="RepoSyncError")

        try:
            head_branch = head or cls.current_branch(repo)
        except Exception as exc:
            return cls._format_error(f"Could not determine head branch: {exc}")

        cmd = ["gh", "pr", "create", "--title", title, "--body", body, "--base", base, "--head", head_branch]
        for reviewer in reviewers or []:
            cmd += ["--reviewer", reviewer]

        # GH_TOKEN is the gh CLI's standard non-interactive auth env var —
        # set it from this server's own GITHUB_TOKEN rather than running
        # an interactive `gh auth login`.
        import os

        result = cls._run(cmd, cwd=repo, timeout=30, env={"GH_TOKEN": os.getenv("GITHUB_TOKEN", "")})
        if result.returncode != 0:
            return cls._format_error(
                f"gh pr create failed: {result.stderr[:500] or result.stdout[:500]}",
                error_type="GhCliError",
            )

        pr_url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        match = _PR_URL_RE.search(pr_url)
        pr_number = int(match.group(1)) if match else None

        logger.info(f"[GITOPS] gh_create_pr | base={base} head={head_branch} | {pr_url}")
        return cls._format_success(pr_url=pr_url, pr_number=pr_number, base=base, head=head_branch)
