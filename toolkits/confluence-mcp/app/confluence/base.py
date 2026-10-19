"""
Shared Confluence base class: HTTP/auth helpers and error formatting
common to every Confluence tool.

Pattern adapted from the sibling Jira MCP toolkit's app/jira/base.py
(JiraToolBase) — Jira and Confluence Cloud share the same Atlassian Cloud
Basic Auth mechanism (email + API token), so the auth helper is a direct
port with the env var names swapped.

API version choices (documented, not accidental):
  - search (CQL) stays on the v1 REST API (`/wiki/rest/api/content/search`)
    since CQL search has no v2 equivalent yet.
  - get_page / update_page use the v2 REST API (`/wiki/api/v2/pages/{id}`)
    since v2 is the current recommended API for page CRUD and has a
    cleaner body/version shape.
  - get_current_user stays on v1 (`/wiki/rest/api/user/current`) — the
    standard, still-current way to resolve the authenticated identity.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_DEFAULT_CONFLUENCE_DOMAIN = "lilly-confluence.atlassian.net"


class ConfluenceToolBase:
    """Shared helpers for Confluence MCP tools. Not instantiated — use as a mixin/base."""

    # ------------------------------------------------------------------
    # Environment / configuration
    # ------------------------------------------------------------------

    @staticmethod
    def validate_env_vars() -> dict:
        """Check that all required environment variables are present."""
        required = ["CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN"]
        missing = [v for v in required if not os.getenv(v)]
        if missing:
            return {
                "success": False,
                "error": f"Missing required environment variables: {', '.join(missing)}",
            }
        return {"success": True}

    @staticmethod
    def _domain() -> str:
        return os.getenv("CONFLUENCE_DOMAIN", _DEFAULT_CONFLUENCE_DOMAIN)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _auth_header() -> dict:
        """Return headers with Basic Auth for the Confluence Cloud REST API."""
        email = os.getenv("CONFLUENCE_EMAIL", "")
        api_token = os.getenv("CONFLUENCE_API_TOKEN", "")

        if not email or not api_token:
            raise Exception(
                "Confluence credentials not configured — set CONFLUENCE_EMAIL and CONFLUENCE_API_TOKEN"
            )

        creds = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        return {
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @classmethod
    def _v1_url(cls, path: str) -> str:
        """Construct a full Confluence v1 REST API URL (/wiki/rest/api/...)."""
        return f"https://{cls._domain()}/wiki/rest/api/{path.lstrip('/')}"

    @classmethod
    def _v2_url(cls, path: str) -> str:
        """Construct a full Confluence v2 REST API URL (/wiki/api/v2/...)."""
        return f"https://{cls._domain()}/wiki/api/v2/{path.lstrip('/')}"

    @classmethod
    def _get(cls, url: str, params: Optional[dict] = None, timeout: int = 10):
        """GET helper returning the parsed JSON body, or raising on error."""
        resp = requests.get(url, headers=cls._auth_header(), params=params, timeout=timeout)
        if resp.status_code != 200:
            raise Exception(f"Confluence GET {url} returned {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    @classmethod
    def _put(cls, url: str, payload: dict, timeout: int = 15):
        """PUT helper returning the parsed JSON body, or raising on error."""
        resp = requests.put(url, headers=cls._auth_header(), json=payload, timeout=timeout)
        if resp.status_code not in (200, 201):
            raise Exception(f"Confluence PUT {url} returned {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    # ------------------------------------------------------------------
    # Error / result formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_error(error: str, error_type: str = "ConfluenceApiError", **extra) -> dict:
        result = {"success": False, "error": error, "error_type": error_type}
        result.update(extra)
        return result

    @staticmethod
    def _format_success(**fields) -> dict:
        return {"success": True, **fields}
