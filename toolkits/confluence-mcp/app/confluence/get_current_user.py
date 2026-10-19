"""
Confluence get-current-user tool — resolve the authenticated service
account's identity via the v1 REST API (/wiki/rest/api/user/current),
still the standard way to do this on Confluence Cloud.

Used by salesforce-documentation-agent to resolve its own account ID for
@mention rendering when the Change Log's contributor is the authenticated
service account itself (Tier 2 of its 3-tier @mention resolution — see
that agent's prompt).
"""

from __future__ import annotations

import logging

from .base import ConfluenceToolBase

logger = logging.getLogger(__name__)


class GetCurrentUserTool(ConfluenceToolBase):
    """Resolve the authenticated Confluence service account's identity."""

    name = "get_current_user"
    description = "Resolve the authenticated user's Confluence account ID, email, and display name."

    @classmethod
    def execute(cls) -> dict:
        """
        Fetch the authenticated service account's own Confluence identity.

        Returns:
            dict with success=True and {account_id, email, display_name,
            account_type, account_status}; or success=False + error.
        """
        try:
            data = cls._get(cls._v1_url("user/current"), timeout=10)
        except Exception as exc:
            return cls._format_error(f"Could not resolve current user: {exc}", error_type="ConfluenceApiError")

        return cls._format_success(
            account_id=data.get("accountId", ""),
            email=data.get("email", ""),
            display_name=data.get("displayName", ""),
            account_type=data.get("accountType", ""),
            account_status=data.get("accountStatus", ""),
        )
