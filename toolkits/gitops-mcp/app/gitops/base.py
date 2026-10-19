"""
Shared git-ops base class: safe subprocess execution, repo clone/sync
management, and error/success formatting common to every git/gh/sf tool.

Pattern mirrors app/jira/base.py (JiraToolBase) and the sibling
salesforce-mcp toolkit's app/salesforce/base.py (SalesforceToolBase) —
single-tenant, env-var credentials, exposed over MCP (FastMCP). The one
structural difference: Jira/Confluence/Salesforce tools call a REST API
directly; this toolkit has no clean REST equivalent for "run git commands
against a working tree," so it shells out to the real `git`/`gh`/`sf` CLIs
via subprocess instead. Every subprocess call here uses an explicit
argument list (never shell=True, never string-interpolated commands) and
an explicit timeout.

## Persistent clone design (read before changing anything here)

This server is the ONE genuinely new component in this migration — the
original local tool ran `git`/`gh` via Claude Code's own Bash tool against
a real local checkout on the engineer's machine. An orchestrator-hosted agent (LangGraph, no local shell)
has no Bash tool, only registered MCP tools, so this server must hold ITS
OWN writable clone of the target Salesforce repo.

Design decision: ONE long-lived clone on a mounted volume
(REPO_CLONE_PATH, default /data/repo), kept in sync via `git fetch` +
checkout/reset at the start of each tool call that touches the working
tree, rather than re-cloning from scratch per request (slow, wasteful, and
defeats the point of a persistent volume). See this toolkit's README.md
for the exact PersistentVolumeClaim spec that deploy-gitops-mcp.yaml needs
added (NOT added by this change — flagged there for a human/different
task to wire up).

## Credential handling

GITHUB_TOKEN (sourced from the GITHUB_PAT secret key per
deploy-gitops-mcp.yaml/external-secrets.yaml) is a service-account PAT
with PUSH RIGHTS to the target Salesforce repo — a materially higher-risk
credential than "whatever's on the engineer's laptop" in the original
local-tool design. This needs its OWN SECURITY SIGN-OFF before this
server goes live with real credentials, independent of the rest of the
orchestrator migration. Flagged here, in the README, and in the CATS deployment
comment — do not soften or drop this flag in any future edit.

The token is never passed as a bare CLI argument (which would leak via
`ps`/process listings). It's injected into the git remote URL
(`https://x-access-token:{token}@github.com/...`) only at the moment a
push actually runs, and into the `gh`/`sf` CLI via the `GH_TOKEN`/stdin-piped
env vars those CLIs already support for non-interactive auth.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_CLONE_PATH = "/data/repo"
_DEFAULT_PROTECTED_BRANCHES = "main,master"
_DEFAULT_SUBPROCESS_TIMEOUT = 60

# Metadata types this toolkit knows how to mirror between the SFDX layout
# (force-app/main/default/<type>/...) and the Metadata API layout
# (src/<type>/...). For every type below the relative path under
# force-app/main/default/ is IDENTICAL to the relative path under src/ —
# this holds for classes, triggers, lwc, aura, flows, layouts, flexipages,
# permissionsets, profiles, customMetadata, quickActions, queues,
# applications, and standardValueSets (see github-commit-agent.json's own
# "Path Mapping" table, replicated here verbatim). It does NOT hold for
# objects/** (SFDX decomposes a custom object into many files under a
# per-object folder; Metadata API uses one file per object — that
# conversion requires `sf project convert`, which this toolkit does not
# attempt) — objects/** is unconditionally excluded, matching the original
# design's Critical Rule #1.
MIRRORED_TOP_LEVEL_DIRS = (
    "classes",
    "triggers",
    "lwc",
    "aura",
    "flows",
    "layouts",
    "flexipages",
    "permissionsets",
    "profiles",
    "customMetadata",
    "quickActions",
    "queues",
    "applications",
    "standardValueSets",
)
EXCLUDED_TOP_LEVEL_DIR = "objects"

SFDX_ROOT = "force-app/main/default"
METADATA_ROOT = "src"


class GitOpsToolBase:
    """Shared helpers for git-ops MCP tools. Not instantiated — use as a mixin/base."""

    # ------------------------------------------------------------------
    # Environment / configuration
    # ------------------------------------------------------------------

    @staticmethod
    def validate_env_vars() -> dict:
        """Check that all required environment variables are present."""
        required = ["GITHUB_TOKEN", "GITHUB_REPO_URL"]
        missing = [v for v in required if not os.getenv(v)]
        if missing:
            return {
                "success": False,
                "error": f"Missing required environment variables: {', '.join(missing)}",
            }
        return {"success": True}

    @staticmethod
    def clone_path() -> Path:
        return Path(os.getenv("REPO_CLONE_PATH", _DEFAULT_CLONE_PATH))

    @staticmethod
    def protected_branches() -> list[str]:
        raw = os.getenv("GITHUB_PROTECTED_BRANCHES", _DEFAULT_PROTECTED_BRANCHES)
        return [b.strip() for b in raw.split(",") if b.strip()]

    @staticmethod
    def github_repo_url() -> str:
        """e.g. 'github.com/EliLillyCo/<the-salesforce-repo>' — operator-set,
        this toolkit has no fixed/known target repo baked in."""
        return os.getenv("GITHUB_REPO_URL", "")

    @staticmethod
    def authenticated_clone_url() -> str:
        """https://x-access-token:{token}@github.com/org/repo.git — the
        standard git-over-HTTPS-with-PAT pattern. Token only ever appears
        embedded in this URL, never as a bare subprocess argument."""
        token = os.getenv("GITHUB_TOKEN", "")
        repo_url = GitOpsToolBase.github_repo_url().removeprefix("https://").removeprefix("http://")
        return f"https://x-access-token:{token}@{repo_url}"

    # ------------------------------------------------------------------
    # Safe subprocess execution
    # ------------------------------------------------------------------

    @classmethod
    def _run(
        cls,
        args: list[str],
        cwd: Optional[Path] = None,
        timeout: int = _DEFAULT_SUBPROCESS_TIMEOUT,
        input_text: Optional[str] = None,
        env: Optional[dict] = None,
    ) -> subprocess.CompletedProcess:
        """
        Run a CLI command safely: explicit argument list (never shell=True,
        never string-interpolated), explicit timeout, stdout/stderr captured.
        Raises on timeout; caller is responsible for checking returncode.
        """
        logger.info(f"[GITOPS] $ {' '.join(args[:3])}{'...' if len(args) > 3 else ''}")
        return subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
            env={**os.environ, **env} if env else None,
        )

    # ------------------------------------------------------------------
    # Repo clone / sync
    # ------------------------------------------------------------------

    @classmethod
    def ensure_repo_cloned_and_synced(cls, branch: Optional[str] = None) -> Path:
        """
        Ensure a writable clone exists at clone_path(), on the correct
        branch, fast-forwarded to origin. Clones fresh if the directory
        doesn't exist yet; otherwise fetches + checks out + resets to the
        given branch (or whatever branch is currently checked out, if
        branch is None — used by tools that operate on "the current
        branch" rather than switching to a specific one).

        Returns the repo's working-tree path.
        """
        env_check = cls.validate_env_vars()
        if not env_check["success"]:
            raise Exception(env_check["error"])

        path = cls.clone_path()
        git_dir = path / ".git"

        if not git_dir.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"[GITOPS] No existing clone at {path} — cloning fresh")
            clone_cmd = ["git", "clone", cls.authenticated_clone_url(), str(path)]
            result = cls._run(clone_cmd, timeout=180)
            if result.returncode != 0:
                raise Exception(f"git clone failed: {result.stderr[:400] or result.stdout[:400]}")
        else:
            # Keep the credential helper fresh even on an existing clone —
            # tokens may have been rotated since this clone was created.
            set_url_cmd = ["git", "remote", "set-url", "origin", cls.authenticated_clone_url()]
            cls._run(set_url_cmd, cwd=path, timeout=15)

            fetch_cmd = ["git", "fetch", "origin"]
            result = cls._run(fetch_cmd, cwd=path, timeout=120)
            if result.returncode != 0:
                raise Exception(f"git fetch failed: {result.stderr[:400] or result.stdout[:400]}")

        if branch:
            # Checkout the branch, creating a local tracking branch from
            # origin/<branch> if it doesn't exist locally yet, then
            # fast-forward it to match origin exactly.
            checkout_cmd = ["git", "checkout", "-B", branch, f"origin/{branch}"]
            result = cls._run(checkout_cmd, cwd=path, timeout=30)
            if result.returncode != 0:
                raise Exception(
                    f"git checkout {branch} failed: {result.stderr[:400] or result.stdout[:400]}"
                )
            reset_cmd = ["git", "reset", "--hard", f"origin/{branch}"]
            result = cls._run(reset_cmd, cwd=path, timeout=30)
            if result.returncode != 0:
                raise Exception(
                    f"git reset --hard origin/{branch} failed: {result.stderr[:400] or result.stdout[:400]}"
                )

        return path

    @classmethod
    def current_branch(cls, repo_path: Path) -> str:
        result = cls._run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path, timeout=10)
        if result.returncode != 0:
            raise Exception(f"git rev-parse failed: {result.stderr[:300]}")
        return result.stdout.strip()

    # ------------------------------------------------------------------
    # Error / result formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_error(error: str, error_type: str = "GitOpsError", **extra) -> dict:
        result = {"success": False, "error": error, "error_type": error_type}
        result.update(extra)
        return result

    @staticmethod
    def _format_success(**fields) -> dict:
        return {"success": True, **fields}
