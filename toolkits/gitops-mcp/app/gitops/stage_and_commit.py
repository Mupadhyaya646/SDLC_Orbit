"""
git_stage_and_commit — git add (explicit src/ paths only, never '.') and
git commit with the approved message.

Hard requirement from the original design (Critical Rule #5 / Gate 2):
NEVER `git add .` or `git add -A`. This tool enforces that by rejecting
any call where `paths` is empty or contains a bare "." or "-A"/"--all".
"""

from __future__ import annotations

import logging

from .base import METADATA_ROOT, GitOpsToolBase

logger = logging.getLogger(__name__)

_FORBIDDEN_PATH_TOKENS = {".", "-A", "--all", "*"}


class GitStageAndCommitTool(GitOpsToolBase):
    """git add (explicit src/ paths only, never '.') and git commit with the approved message."""

    name = "git_stage_and_commit"
    description = (
        "git add (explicit src/ paths only, never '.') and git commit with "
        "the approved message."
    )

    @classmethod
    def execute(cls, paths: list[str], message: str, branch: str | None = None) -> dict:
        """
        Args:
            paths: explicit src/-relative paths to stage (e.g.
                ["src/classes/Foo.cls", "src/classes/Foo.cls-meta.xml"]) —
                normally the "mirrored" list git_mirror_sfdx_to_metadata
                just returned, with the src/ prefix added. Must be
                non-empty and must not contain "." / "-A" / "--all" / "*".
            message: the approved commit message (Gate 2).
            branch: branch to sync the clone to first.

        Returns:
            dict with success flag, branch, commit_sha (short), staged
            (the paths actually staged).
        """
        if not paths:
            return cls._format_error("paths must be a non-empty list", error_type="ValidationError")
        if any(p.strip() in _FORBIDDEN_PATH_TOKENS for p in paths):
            return cls._format_error(
                "paths must be explicit file paths — 'git add .' / '-A' / '--all' / '*' are forbidden "
                "by design (original Critical Rule #5: stage selectively, never the whole tree).",
                error_type="ValidationError",
            )
        if not message or not message.strip():
            return cls._format_error("message is required", error_type="ValidationError")

        try:
            repo = cls.ensure_repo_cloned_and_synced(branch=branch)
        except Exception as exc:
            return cls._format_error(f"Could not sync repo clone: {exc}", error_type="RepoSyncError")

        # Normalize: tool contract says src/-relative in the description,
        # but accept paths already prefixed with src/ or bare (relative to
        # METADATA_ROOT) — this is purely a convenience for the calling
        # agent, which may pass either shape depending on how it tracked
        # the mirror step's output.
        normalized = [p if p.startswith(f"{METADATA_ROOT}/") else f"{METADATA_ROOT}/{p}" for p in paths]

        add_cmd = ["git", "add", "--"] + normalized
        result = cls._run(add_cmd, cwd=repo, timeout=30)
        if result.returncode != 0:
            return cls._format_error(f"git add failed: {result.stderr[:400] or result.stdout[:400]}")

        commit_cmd = ["git", "commit", "-m", message]
        result = cls._run(commit_cmd, cwd=repo, timeout=30)
        if result.returncode != 0:
            return cls._format_error(f"git commit failed: {result.stderr[:400] or result.stdout[:400]}")

        sha_result = cls._run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, timeout=10)
        commit_sha = sha_result.stdout.strip() if sha_result.returncode == 0 else None

        try:
            current_branch = cls.current_branch(repo)
        except Exception:
            current_branch = branch or "unknown"

        logger.info(f"[GITOPS] git_stage_and_commit | branch={current_branch} | sha={commit_sha}")
        return cls._format_success(
            branch=current_branch,
            commit_sha=commit_sha,
            staged=normalized,
        )
