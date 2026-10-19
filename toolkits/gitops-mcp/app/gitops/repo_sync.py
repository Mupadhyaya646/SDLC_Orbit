"""
Thin re-export module: `ensure_repo_cloned_and_synced` as a standalone
function (not a classmethod), for tool modules that prefer
`from .repo_sync import ensure_repo_cloned_and_synced` over reaching into
GitOpsToolBase directly. The real implementation lives in base.py
(GitOpsToolBase.ensure_repo_cloned_and_synced) since it needs the same
env-var/config helpers (clone_path, authenticated_clone_url) that every
other tool's base-class methods also use — duplicating it here would
just be two copies of the same logic to keep in sync.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base import GitOpsToolBase


def ensure_repo_cloned_and_synced(branch: Optional[str] = None) -> Path:
    return GitOpsToolBase.ensure_repo_cloned_and_synced(branch=branch)
