"""
git_mirror_sfdx_to_metadata — copy approved SFDX-layout files into
Metadata API src/ layout (or delete on removal).

Same relative-path assumption as diff.py (see base.py's module docstring
and MIRRORED_TOP_LEVEL_DIRS): for every covered metadata type, the
relative path under force-app/main/default/ is identical to the relative
path under src/. objects/** is never touched (not in MIRRORED_TOP_LEVEL_DIRS).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .base import METADATA_ROOT, MIRRORED_TOP_LEVEL_DIRS, SFDX_ROOT, GitOpsToolBase

logger = logging.getLogger(__name__)


class GitMirrorSfdxToMetadataTool(GitOpsToolBase):
    """Copy approved SFDX-layout files into Metadata API src/ layout (or delete on removal)."""

    name = "git_mirror_sfdx_to_metadata"
    description = (
        "Copy approved SFDX-layout files into Metadata API src/ layout "
        "(or delete on removal)."
    )

    @classmethod
    def execute(cls, file_paths: list[str], branch: str | None = None) -> dict:
        """
        Args:
            file_paths: force-app-relative paths to mirror (the subset of
                git_diff's output the user approved at Gate 1/Gate 2 — e.g.
                ["classes/Foo.cls", "classes/Foo.cls-meta.xml"]). Each path
                must be under one of base.py's MIRRORED_TOP_LEVEL_DIRS;
                anything under objects/ or outside the known mirrored
                types is rejected per-file (not a hard failure for the
                whole call) with a reason in `skipped`.
            branch: branch to sync the clone to first.

        Returns:
            dict with success flag, branch, mirrored (list of {path,
            action: "copied"|"deleted"}), skipped (list of {path, reason}).
        """
        if not file_paths:
            return cls._format_error("file_paths must be a non-empty list", error_type="ValidationError")

        try:
            repo = cls.ensure_repo_cloned_and_synced(branch=branch)
        except Exception as exc:
            return cls._format_error(f"Could not sync repo clone: {exc}", error_type="RepoSyncError")

        sfdx_root = repo / SFDX_ROOT
        metadata_root = repo / METADATA_ROOT

        mirrored = []
        skipped = []

        for rel_path in file_paths:
            top_dir = rel_path.split("/", 1)[0] if "/" in rel_path else rel_path
            if top_dir not in MIRRORED_TOP_LEVEL_DIRS:
                skipped.append({"path": rel_path, "reason": f"not a mirrored metadata type ({top_dir})"})
                continue

            sfdx_file = sfdx_root / rel_path
            metadata_file = metadata_root / rel_path

            if sfdx_file.exists():
                metadata_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(sfdx_file, metadata_file)
                mirrored.append({"path": rel_path, "action": "copied"})
            elif metadata_file.exists():
                # Deleted in force-app, still present in src/ — mirror the deletion.
                metadata_file.unlink()
                mirrored.append({"path": rel_path, "action": "deleted"})
            else:
                skipped.append({"path": rel_path, "reason": "not found in force-app or src/"})

        try:
            current_branch = cls.current_branch(repo)
        except Exception:
            current_branch = branch or "unknown"

        logger.info(
            f"[GITOPS] git_mirror_sfdx_to_metadata | branch={current_branch} | "
            f"mirrored={len(mirrored)} skipped={len(skipped)}"
        )
        return cls._format_success(branch=current_branch, mirrored=mirrored, skipped=skipped)
