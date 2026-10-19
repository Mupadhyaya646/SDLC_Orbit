"""
git_push — push HEAD to its own remote tracking branch on origin, with a
hard refusal if the current branch is protected.
"""

from __future__ import annotations

import logging

from .base import GitOpsToolBase

logger = logging.getLogger(__name__)


class GitPushTool(GitOpsToolBase):
    """git push to the current (non-protected) feature branch."""

    name = "git_push"
    description = "git push to the current (non-protected) feature branch."

    @classmethod
    def execute(cls, branch: str | None = None) -> dict:
        """
        Args:
            branch: branch to push. If omitted, pushes whatever branch the
                persistent clone currently has checked out (the normal
                case — this tool runs right after git_stage_and_commit on
                the same clone, same branch).

        Returns:
            dict with success flag, branch, remote_url (https form,
            credential-free) on success; success=False + error on
            failure (including the protected-branch refusal and git's own
            push error, e.g. non-fast-forward).
        """
        try:
            repo = cls.ensure_repo_cloned_and_synced(branch=branch)
        except Exception as exc:
            return cls._format_error(f"Could not sync repo clone: {exc}", error_type="RepoSyncError")

        try:
            target_branch = branch or cls.current_branch(repo)
        except Exception as exc:
            return cls._format_error(f"Could not determine current branch: {exc}")

        protected = cls.protected_branches()
        if target_branch in protected:
            return cls._format_error(
                f"Refusing to push to protected branch '{target_branch}' "
                f"(protected: {', '.join(protected)}). Create/switch to a feature branch first.",
                error_type="ProtectedBranchError",
            )

        # Credential already embedded via ensure_repo_cloned_and_synced's
        # remote set-url step — push by branch name only, no token in argv.
        push_cmd = ["git", "push", "origin", target_branch]
        result = cls._run(push_cmd, cwd=repo, timeout=60)
        if result.returncode != 0:
            return cls._format_error(
                f"git push failed: {result.stderr[:500] or result.stdout[:500]}",
                error_type="GitPushError",
                branch=target_branch,
            )

        repo_url_credential_free = cls.github_repo_url()
        logger.info(f"[GITOPS] git_push | branch={target_branch} | SUCCESS")
        return cls._format_success(branch=target_branch, remote_url=f"https://{repo_url_credential_free}")
