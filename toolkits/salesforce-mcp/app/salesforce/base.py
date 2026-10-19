"""
Shared Salesforce base class: OAuth2 (username-password flow) auth, Tooling
API HTTP helpers, and error formatting common to every Salesforce tool.

Pattern mirrors app/jira/base.py (JiraToolBase) — single-tenant, env-var
credentials, exposes tools over MCP (FastMCP) rather than gRPC.

Auth: Salesforce's OAuth2 "username-password" flow (the standard
non-interactive server-to-server grant — no browser redirect, no refresh
token management needed beyond re-requesting a token when one expires).
POST {SF_LOGIN_URL}/services/oauth2/token with:
  grant_type=password
  client_id=<connected app consumer key>
  client_secret=<connected app consumer secret>
  username=<SF_USERNAME>
  password=<SF_PASSWORD><SF_SECURITY_TOKEN>   (concatenated, no separator —
                                                standard Salesforce convention)

Required env vars (see this toolkit's README.md for the full list — the
CATS deploy-salesforce-mcp.yaml currently only wires SF_USERNAME/SF_LOGIN_URL
and needs updating to add the rest):
  SF_LOGIN_URL        e.g. "https://login.salesforce.com" or a My Domain URL
  SF_USERNAME         integration user's username
  SF_PASSWORD         integration user's password
  SF_SECURITY_TOKEN   integration user's security token (reset via Setup ->
                       My Personal Information -> Reset My Security Token)
  SF_CLIENT_ID        connected app consumer key
  SF_CLIENT_SECRET    connected app consumer secret
  SF_API_VERSION      optional, defaults to "61.0"
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_DEFAULT_API_VERSION = "61.0"

# Module-level token cache (one process = one integration-user session,
# matches the single-tenant design of this toolkit server).
_token_cache: dict = {"access_token": None, "instance_url": None, "obtained_at": 0.0}
_TOKEN_TTL_SECONDS = 1800  # Salesforce session tokens are long-lived, but
                            # re-auth periodically rather than caching forever
                            # in case the integration user's session is revoked.


class SalesforceToolBase:
    """Shared helpers for Salesforce MCP tools. Not instantiated — use as a mixin/base."""

    # ------------------------------------------------------------------
    # Environment / configuration
    # ------------------------------------------------------------------

    @staticmethod
    def validate_env_vars() -> dict:
        """Check that all required environment variables are present."""
        required = [
            "SF_LOGIN_URL",
            "SF_USERNAME",
            "SF_PASSWORD",
            "SF_SECURITY_TOKEN",
            "SF_CLIENT_ID",
            "SF_CLIENT_SECRET",
        ]
        missing = [v for v in required if not os.getenv(v)]
        if missing:
            return {
                "success": False,
                "error": f"Missing required environment variables: {', '.join(missing)}",
            }
        return {"success": True}

    @staticmethod
    def _api_version() -> str:
        return os.getenv("SF_API_VERSION", _DEFAULT_API_VERSION)

    # ------------------------------------------------------------------
    # OAuth2 username-password flow
    # ------------------------------------------------------------------

    @classmethod
    def _authenticate(cls) -> dict:
        """
        Request a fresh access token via the OAuth2 username-password grant.
        Returns {"access_token": ..., "instance_url": ...} and populates the
        module-level cache.
        """
        login_url = os.getenv("SF_LOGIN_URL", "https://login.salesforce.com").rstrip("/")
        payload = {
            "grant_type": "password",
            "client_id": os.getenv("SF_CLIENT_ID", ""),
            "client_secret": os.getenv("SF_CLIENT_SECRET", ""),
            "username": os.getenv("SF_USERNAME", ""),
            "password": f"{os.getenv('SF_PASSWORD', '')}{os.getenv('SF_SECURITY_TOKEN', '')}",
        }
        resp = requests.post(f"{login_url}/services/oauth2/token", data=payload, timeout=15)
        if resp.status_code != 200:
            raise Exception(
                f"Salesforce OAuth2 token request failed ({resp.status_code}): {resp.text[:300]}"
            )
        data = resp.json()
        _token_cache["access_token"] = data["access_token"]
        _token_cache["instance_url"] = data["instance_url"]
        _token_cache["obtained_at"] = time.time()
        logger.info(f"[SF] Authenticated — instance_url={data['instance_url']}")
        return data

    @classmethod
    def _ensure_auth(cls) -> None:
        """Authenticate if we have no cached token or it's past its TTL."""
        if not _token_cache["access_token"] or (time.time() - _token_cache["obtained_at"]) > _TOKEN_TTL_SECONDS:
            cls._authenticate()

    @classmethod
    def _auth_header(cls) -> dict:
        """Return headers with Bearer auth for the Salesforce REST/Tooling API."""
        cls._ensure_auth()
        return {
            "Authorization": f"Bearer {_token_cache['access_token']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @classmethod
    def _instance_url(cls) -> str:
        cls._ensure_auth()
        return _token_cache["instance_url"]

    # ------------------------------------------------------------------
    # HTTP helpers (standard REST + Tooling API, re-auth once on 401)
    # ------------------------------------------------------------------

    @classmethod
    def _rest_url(cls, path: str) -> str:
        """Construct a full standard REST API URL (/services/data/vXX.0/...)."""
        return f"{cls._instance_url()}/services/data/v{cls._api_version()}/{path.lstrip('/')}"

    @classmethod
    def _tooling_url(cls, path: str) -> str:
        """Construct a full Tooling API URL (/services/data/vXX.0/tooling/...)."""
        return f"{cls._instance_url()}/services/data/v{cls._api_version()}/tooling/{path.lstrip('/')}"

    @classmethod
    def _request(cls, method: str, url_fn, path: str, retry_on_401: bool = True, **kwargs):
        """Shared request runner: builds the URL via url_fn, attaches auth,
        retries once on 401 (expired/invalid session) by forcing re-auth."""
        timeout = kwargs.pop("timeout", 15)
        resp = requests.request(method, url_fn(path), headers=cls._auth_header(), timeout=timeout, **kwargs)
        if resp.status_code == 401 and retry_on_401:
            logger.warning("[SF] 401 — forcing re-authentication and retrying once")
            cls._authenticate()
            resp = requests.request(method, url_fn(path), headers=cls._auth_header(), timeout=timeout, **kwargs)
        return resp

    @classmethod
    def _rest_get(cls, path: str, params: Optional[dict] = None, timeout: int = 15):
        resp = cls._request("GET", cls._rest_url, path, params=params, timeout=timeout)
        if resp.status_code != 200:
            raise Exception(f"Salesforce REST GET {path} returned {resp.status_code}: {resp.text[:400]}")
        return resp.json()

    @classmethod
    def _tooling_get(cls, path: str, params: Optional[dict] = None, timeout: int = 15):
        resp = cls._request("GET", cls._tooling_url, path, params=params, timeout=timeout)
        if resp.status_code != 200:
            raise Exception(f"Salesforce Tooling GET {path} returned {resp.status_code}: {resp.text[:400]}")
        return resp.json()

    @classmethod
    def _tooling_post(cls, path: str, payload: dict, timeout: int = 30):
        resp = cls._request("POST", cls._tooling_url, path, json=payload, timeout=timeout)
        if resp.status_code not in (200, 201):
            raise Exception(f"Salesforce Tooling POST {path} returned {resp.status_code}: {resp.text[:400]}")
        return resp.json() if resp.text else {}

    @classmethod
    def _tooling_patch(cls, path: str, payload: dict, timeout: int = 30):
        resp = cls._request("PATCH", cls._tooling_url, path, json=payload, timeout=timeout)
        if resp.status_code not in (200, 204):
            raise Exception(f"Salesforce Tooling PATCH {path} returned {resp.status_code}: {resp.text[:400]}")
        return resp.json() if resp.text else {}

    @classmethod
    def _tooling_query(cls, soql: str, timeout: int = 15) -> list[dict]:
        """Run a Tooling API SOQL query (GET /tooling/query?q=...) and return records."""
        data = cls._tooling_get("query", params={"q": soql}, timeout=timeout)
        return data.get("records", [])

    # ------------------------------------------------------------------
    # Error / result formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_error(error: str, error_type: str = "SalesforceApiError", **extra) -> dict:
        result = {"success": False, "error": error, "error_type": error_type}
        result.update(extra)
        return result

    @staticmethod
    def _format_success(**fields) -> dict:
        return {"success": True, **fields}
