"""
git_diff — find what in force-app/main/default/ (SFDX layout, where
Claude/humans edited files) hasn't been mirrored into src/ (Metadata API
layout) yet.

NOT a plain `git diff` between two directories — it's a working-tree
comparison: for every file under force-app/main/default/<mirrored-type>/
(see base.py's MIRRORED_TOP_LEVEL_DIRS), check whether src/<same-relative-
path> exists with identical content. objects/** is always excluded (see
base.py's module docstring for why — SFDX decomposes custom objects,
Metadata API doesn't, that conversion needs `sf project convert` which
this toolkit does not attempt).
"""

from __future__ import annotations

import filecmp
import logging
from pathlib import Path

from .base import EXCLUDED_TOP_LEVEL_DIR, METADATA_ROOT, MIRRORED_TOP_LEVEL_DIRS, SFDX_ROOT, GitOpsToolBase

logger = logging.getLogger(__name__)


class GitDiffTool(GitOpsToolBase):
    """git status + content diff between force-app/main/default and src/, excluding objects/**."""

    name = "git_diff"
    description = (
        "git status + content diff between force-app/main/default and src/, "
        "excluding objects/**."
    )

    @classmethod
    def execute(cls, branch: str | None = None) -> dict:
        """
        Args:
            branch: branch to sync the clone to before diffing. If omitted,
                diffs whatever branch the persistent clone is currently on
                (the common case mid-workflow, after a prior tool call
                already checked out the feature branch).

        Returns:
            dict with success flag, branch, and files: a list of
            {path, status} where path is the force-app-relative path
            (e.g. "classes/Foo.cls") and status is one of:
              "new"       — exists in force-app, not in src/
              "modified"  — exists in both, content differs
              "deleted"   — exists in src/, not in force-app (force-app
                             delete not yet mirrored)
              "unchanged" — exists in both, content identical (not
                             returned — only files needing action are listed)
        """
        try:
            repo = cls.ensure_repo_cloned_and_synced(branch=branch)
        except Exception as exc:
            return cls._format_error(f"Could not sync repo clone: {exc}", error_type="RepoSyncError")

        sfdx_root = repo / SFDX_ROOT
        metadata_root = repo / METADATA_ROOT

        if not sfdx_root.exists():
            return cls._format_error(f"{SFDX_ROOT} does not exist in the clone", error_type="ValidationError")

        files: list[dict] = []
        seen_relative_paths: set[str] = set()

        for top_dir in MIRRORED_TOP_LEVEL_DIRS:
            sfdx_subdir = sfdx_root / top_dir
            if not sfdx_subdir.exists():
                continue
            for sfdx_file in sfdx_subdir.rglob("*"):
                if sfdx_file.is_dir():
                    continue
                rel_path = sfdx_file.relative_to(sfdx_root).as_posix()
                seen_relative_paths.add(rel_path)
                metadata_file = metadata_root / rel_path

                if not metadata_file.exists():
                    files.append({"path": rel_path, "status": "new"})
                elif not filecmp.cmp(sfdx_file, metadata_file, shallow=False):
                    files.append({"path": rel_path, "status": "modified"})
                # identical files are omitted — nothing to act on

        # Deletions: a file exists under src/<mirrored-type>/ but no longer
        # exists under force-app/main/default/<mirrored-type>/.
        for top_dir in MIRRORED_TOP_LEVEL_DIRS:
            metadata_subdir = metadata_root / top_dir
            if not metadata_subdir.exists():
                continue
            for metadata_file in metadata_subdir.rglob("*"):
                if metadata_file.is_dir():
                    continue
                rel_path = metadata_file.relative_to(metadata_root).as_posix()
                if rel_path in seen_relative_paths:
                    continue
                sfdx_file = sfdx_root / rel_path
                if not sfdx_file.exists():
                    files.append({"path": rel_path, "status": "deleted"})

        try:
            current_branch = cls.current_branch(repo)
        except Exception:
            current_branch = branch or "unknown"

        logger.info(f"[GITOPS] git_diff | branch={current_branch} | {len(files)} file(s) need action")
        return cls._format_success(
            branch=current_branch,
            files=files,
            excluded_dir=EXCLUDED_TOP_LEVEL_DIR,
            mirrored_types=list(MIRRORED_TOP_LEVEL_DIRS),
        )
