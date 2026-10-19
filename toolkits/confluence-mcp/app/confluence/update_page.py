"""
Confluence update-page tool — update an existing page's body via the v2
REST API (/wiki/api/v2/pages/{id}), used only for the Change Log row
append pattern (per salesforce-documentation-agent's "NEVER modify body
content of an existing page — Change Log row only" rule).

This tool is a thin, correct wrapper around the real update call — it does
NOT construct the modified storage-format XHTML itself (e.g. inserting a
<tr> into an existing <table>). The calling agent is responsible for
building the full new body string (by reading the current body via
get_page, inserting its new row, and passing the complete result here).
This keeps the tool's contract simple and auditable: what you pass as
new_body_storage is exactly what gets written.
"""

from __future__ import annotations

import logging
from typing import Optional

from .base import ConfluenceToolBase

logger = logging.getLogger(__name__)


class UpdatePageTool(ConfluenceToolBase):
    """Update an existing Confluence page's body (optimistic-locked by version)."""

    name = "update_page"
    description = "Update an existing Confluence page's body (Change Log row append only)."

    @classmethod
    def execute(
        cls,
        page_id: str,
        new_body_storage: str,
        version_number: int,
        title: Optional[str] = None,
    ) -> dict:
        """
        Update a Confluence page's body.

        Args:
            page_id: Confluence page ID. Required.
            new_body_storage: The FULL new body content, in Confluence storage
                format (XHTML). Must be the complete body — this call replaces
                the entire body, it does not merge/patch. Required.
            version_number: The page's CURRENT version number (as returned by
                get_page) — Confluence requires optimistic-locking via
                version+1; this tool handles the +1 increment internally.
                Required.
            title: Optional new title. If omitted, the current title is kept
                (fetched via get_page internally if not supplied).

        Returns:
            dict with success=True and {id, version, url}; or success=False + error.
        """
        if not page_id or not str(page_id).strip():
            return cls._format_error("page_id is required", error_type="ValidationError")
        if not new_body_storage:
            return cls._format_error("new_body_storage is required", error_type="ValidationError")
        if version_number is None:
            return cls._format_error("version_number is required", error_type="ValidationError")

        page_id = str(page_id).strip()

        if not title:
            try:
                current = cls._get(cls._v2_url(f"pages/{page_id}"), timeout=10)
                title = current.get("title", "")
            except Exception as exc:
                return cls._format_error(
                    f"Could not fetch current title for page {page_id} (required when title is omitted): {exc}",
                    error_type="ConfluenceApiError",
                )

        payload = {
            "id": page_id,
            "status": "current",
            "title": title,
            "body": {
                "representation": "storage",
                "value": new_body_storage,
            },
            "version": {"number": int(version_number) + 1},
        }

        try:
            data = cls._put(cls._v2_url(f"pages/{page_id}"), payload, timeout=20)
        except Exception as exc:
            return cls._format_error(f"Could not update page {page_id}: {exc}", error_type="ConfluenceApiError")

        domain = cls._domain()
        webui_link = (data.get("_links") or {}).get("webui", "")

        logger.info(f"[CONFLUENCE] update_page({page_id}) -> version {(data.get('version') or {}).get('number')}")
        return cls._format_success(
            id=data.get("id"),
            version=(data.get("version") or {}).get("number"),
            url=f"https://{domain}/wiki{webui_link}" if webui_link else f"https://{domain}/wiki/pages/viewpage.action?pageId={page_id}",
        )
