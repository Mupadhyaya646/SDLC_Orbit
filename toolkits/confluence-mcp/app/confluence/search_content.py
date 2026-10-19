"""
Confluence search tool — CQL (Confluence Query Language) search over v1's
/wiki/rest/api/content/search, since CQL search has no v2 API equivalent.

Used by salesforce-design-agent (live Confluence search replacing the
original local tool's pre-built agent-functional-memory/ RAG cache) and
salesforce-documentation-agent (find an existing design doc page by title).
"""

from __future__ import annotations

import logging
from typing import Optional

from .base import ConfluenceToolBase

logger = logging.getLogger(__name__)


class SearchContentTool(ConfluenceToolBase):
    """Search Confluence content via CQL."""

    name = "search_content"
    description = "Search Confluence (CQL) for pages matching a query, optionally scoped to a space."

    @classmethod
    def execute(cls, query: str, space_key: Optional[str] = None, limit: int = 10) -> dict:
        """
        Search Confluence pages by free text, optionally scoped to a space.

        Args:
            query: Free text to search for (matched against page title/body via CQL `text ~`).
            space_key: Optional Confluence space key to scope the search to.
            limit: Maximum number of results to return (default 10).

        Returns:
            dict with success=True and a `results` list of
            {id, title, space_key, url, excerpt}; or success=False + error.
        """
        if not query or not query.strip():
            return cls._format_error("query is required", error_type="ValidationError")

        query = query.strip()
        # Escape double quotes in the query to keep the CQL string literal valid.
        escaped_query = query.replace('"', '\\"')
        cql = f'type = "page" AND text ~ "{escaped_query}"'
        if space_key:
            cql += f' AND space = "{space_key.strip()}"'

        try:
            data = cls._get(
                cls._v1_url("content/search"),
                params={"cql": cql, "limit": limit, "expand": "space"},
                timeout=15,
            )
        except Exception as exc:
            return cls._format_error(f"Could not search Confluence: {exc}", error_type="ConfluenceApiError")

        domain = cls._domain()
        results = []
        for item in data.get("results", []):
            page_id = item.get("id")
            title = item.get("title", "")
            space = (item.get("space") or {}).get("key", space_key or "")
            webui = (item.get("_links") or {}).get("webui", "")
            excerpt = item.get("excerpt", "")
            results.append({
                "id": page_id,
                "title": title,
                "space_key": space,
                "url": f"https://{domain}/wiki{webui}" if webui else f"https://{domain}/wiki/pages/viewpage.action?pageId={page_id}",
                "excerpt": excerpt,
            })

        logger.info(f"[CONFLUENCE] search_content({query!r}) -> {len(results)} result(s)")
        return cls._format_success(results=results, total=data.get("size", len(results)))
