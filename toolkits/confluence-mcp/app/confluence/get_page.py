"""
Confluence get-page tool — fetch a page's full content by ID via the v2
REST API (/wiki/api/v2/pages/{id}), the current recommended API for page
reads.

Used by salesforce-design-agent (read a matching design doc in full after
search_content finds it) and salesforce-documentation-agent (fetch current
body + version before appending a Change Log row via update_page).
"""

from __future__ import annotations

import logging

from .base import ConfluenceToolBase

logger = logging.getLogger(__name__)


class GetPageTool(ConfluenceToolBase):
    """Fetch a single Confluence page's content and version by ID."""

    name = "get_page"
    description = "Read a Confluence page's full body (storage format) and version by page ID."

    @classmethod
    def execute(cls, page_id: str, body_format: str = "storage") -> dict:
        """
        Fetch a Confluence page's content by ID.

        Args:
            page_id: Confluence page ID (e.g. "2070478901"). Required.
            body_format: Body representation to return — "storage" (Confluence
                storage-format XHTML, the default and the format update_page
                expects back) or "view" (rendered HTML). Default "storage".

        Returns:
            dict with success=True and {id, title, space_id, version, body,
            url}; or success=False + error.
        """
        if not page_id or not str(page_id).strip():
            return cls._format_error("page_id is required", error_type="ValidationError")

        page_id = str(page_id).strip()

        try:
            data = cls._get(
                cls._v2_url(f"pages/{page_id}"),
                params={"body-format": body_format},
                timeout=15,
            )
        except Exception as exc:
            return cls._format_error(f"Could not fetch page {page_id}: {exc}", error_type="ConfluenceApiError")

        body_obj = (data.get("body") or {}).get(body_format, {})
        domain = cls._domain()
        webui_link = (data.get("_links") or {}).get("webui", "")

        return cls._format_success(
            id=data.get("id"),
            title=data.get("title", ""),
            space_id=data.get("spaceId"),
            version=(data.get("version") or {}).get("number"),
            body=body_obj.get("value", ""),
            url=f"https://{domain}/wiki{webui_link}" if webui_link else f"https://{domain}/wiki/pages/viewpage.action?pageId={page_id}",
        )
