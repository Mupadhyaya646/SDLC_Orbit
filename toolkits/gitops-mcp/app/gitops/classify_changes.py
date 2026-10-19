"""
git_classify_changes — classify each changed file as Claude-generated vs
manual.

Design adaptation (documented, not an oversight): the original local-tool
design classified changes by cross-referencing session memory files
(developer-memory.md, admin-memory.md, unit-testing-memory.md) that lived
on the same filesystem as the git working tree. Under the LangGraph orchestrator, that
session state instead lives in the separate SDLC_Orbit API (sdlc_orbit/)
app's Postgres `handoff_payloads` table — this MCP server has no database
connection to it and is not meant to acquire one (it would couple two
independently-deployed services together for no architectural benefit).

Instead, this tool accepts the list of AI-authored file paths as a
PARAMETER. The calling agent (github-commit-agent, orchestrated by the
pipeline that DOES have access to the handoff data via its own LangGraph
session context) passes that list in explicitly. This tool's only job is
the actual set-comparison against git_diff's file list — a pure function,
no I/O beyond the diff itself.
"""

from __future__ import annotations

import logging

from .base import GitOpsToolBase
from .diff import GitDiffTool

logger = logging.getLogger(__name__)


class GitClassifyChangesTool(GitOpsToolBase):
    """Classify changed files as Claude-generated vs manual against session handoff records."""

    name = "git_classify_changes"
    description = (
        "Classify changed files as Claude-generated vs manual against session "
        "handoff records."
    )

    @classmethod
    def execute(cls, ai_authored_paths: list[str], branch: str | None = None) -> dict:
        """
        Args:
            ai_authored_paths: force-app-relative paths (same shape as
                git_diff's "path" field) that the calling agent/orchestrator
                knows were written by a Claude agent this session (sourced
                from the pipeline's own handoff_payloads record — not
                looked up by this tool). An empty list means "no
                SESSION_ID"/no recorded AI authorship — per the original
                design's rule, that means ALL changes are treated as manual.
            branch: branch to diff against (passed through to git_diff).

        Returns:
            dict with success flag, branch, claude_generated (list of
            {path, status}), manual (list of {path, status}).
        """
        diff_result = GitDiffTool.execute(branch=branch)
        if not diff_result.get("success"):
            return diff_result

        ai_set = set(ai_authored_paths or [])
        claude_generated = []
        manual = []

        for f in diff_result["files"]:
            if f["path"] in ai_set:
                claude_generated.append(f)
            else:
                manual.append(f)

        logger.info(
            f"[GITOPS] git_classify_changes | branch={diff_result['branch']} | "
            f"claude={len(claude_generated)} manual={len(manual)}"
        )
        return cls._format_success(
            branch=diff_result["branch"],
            claude_generated=claude_generated,
            manual=manual,
            no_session_data=len(ai_set) == 0,
        )
