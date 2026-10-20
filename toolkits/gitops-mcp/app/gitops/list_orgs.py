"""
sf_list_orgs — equivalent of `sf org list --all --json`, used by
github-commit-agent's Gate 5 Step 2 to show the numbered target-org table.

Auth note: unlike this toolkit's other tools, this one shells out to the
`sf` CLI rather than git/gh — it needs the SAME Salesforce OAuth2
credentials the sibling salesforce-mcp toolkit server already uses
(SF_LOGIN_URL/SF_USERNAME/SF_PASSWORD/SF_SECURITY_TOKEN/SF_CLIENT_ID/
SF_CLIENT_SECRET — identical env var names, reused here rather than
inventing a second set, since both servers authenticate to the same
Salesforce org(s)). See this toolkit's README for the full env var list.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess

import requests

from .base import GitOpsToolBase

logger = logging.getLogger(__name__)

_SF_CLI_TIMEOUT_SECONDS = 30
_DEFAULT_SF_LOGIN_URL = "https://test.salesforce.com"


class SfListOrgsTool(GitOpsToolBase):
    """Equivalent of `sf org list --all --json`, used to show the numbered target-org table at Gate 5 Step 2."""

    name = "sf_list_orgs"
    description = (
        "Equivalent of `sf org list --all --json`, used to show the numbered "
        "target-org table at Gate 5 Step 2."
    )

    @classmethod
    def _sf_env_check(cls) -> dict:
        required = ["SF_LOGIN_URL", "SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN", "SF_CLIENT_ID", "SF_CLIENT_SECRET"]
        missing = [v for v in required if not os.getenv(v)]
        if missing:
            return {"success": False, "error": f"Missing required environment variables: {', '.join(missing)}"}
        return {"success": True}

    @classmethod
    def _authenticate_this_org(cls) -> dict:
        """Independent OAuth2 username-password auth — this tool does not
        import the sibling salesforce-mcp toolkit's module (separate
        container, separate process), so it re-implements the same token
        request using the same env var names."""
        login_url = os.getenv("SF_LOGIN_URL", _DEFAULT_SF_LOGIN_URL).rstrip("/")
        payload = {
            "grant_type": "password",
            "client_id": os.getenv("SF_CLIENT_ID", ""),
            "client_secret": os.getenv("SF_CLIENT_SECRET", ""),
            "username": os.getenv("SF_USERNAME", ""),
            "password": f"{os.getenv('SF_PASSWORD', '')}{os.getenv('SF_SECURITY_TOKEN', '')}",
        }
        resp = requests.post(f"{login_url}/services/oauth2/token", data=payload, timeout=15)
        if resp.status_code != 200:
            raise Exception(f"Salesforce OAuth2 token request failed ({resp.status_code}): {resp.text[:300]}")
        return resp.json()

    @classmethod
    def execute(cls) -> dict:
        """
        Lists the Salesforce org(s) this toolkit's own service-account
        credentials authenticate to, in the same shape `sf org list --all
        --json` would return (alias, username, connectedStatus) — the
        agent presents this as the numbered table for Gate 5's target-org
        selection.

        Note: since this server authenticates with a single fixed set of
        env-var credentials (one integration user), there is exactly ONE
        "org" to list unless that integration user's `sf` CLI local auth
        store (if pre-authenticated via `sf org login` as part of this
        server's operational setup — see README) has additional orgs
        registered. This tool checks BOTH: the single OAuth2-authenticated
        org from env vars, AND whatever `sf org list --all --json` reports
        if the `sf` CLI is installed and has its own pre-authenticated
        orgs — merging both lists (de-duplicated by username) so a real
        multi-org pipeline (SIT/UAT/dev) can be validated against, not
        just the one org this server's own env vars point at.

        Returns:
            dict with success flag, orgs: list of {alias, username,
            connected_status}.
        """
        orgs: list[dict] = []
        errors: list[str] = []

        env_check = cls._sf_env_check()
        if env_check["success"]:
            try:
                token_data = cls._authenticate_this_org()
                orgs.append(
                    {
                        "alias": None,
                        "username": os.getenv("SF_USERNAME", ""),
                        "connected_status": "Connected",
                        "instance_url": token_data.get("instance_url"),
                    }
                )
            except Exception as exc:
                errors.append(f"env-var org auth failed: {exc}")
        else:
            errors.append(env_check["error"])

        if shutil.which("sf") is not None:
            try:
                result = subprocess.run(
                    ["sf", "org", "list", "--all", "--json"],
                    capture_output=True,
                    text=True,
                    timeout=_SF_CLI_TIMEOUT_SECONDS,
                )
                parsed = json.loads(result.stdout) if result.stdout else {}
                cli_result = parsed.get("result", {})
                known_usernames = {o["username"] for o in orgs}
                for org_list_key in ("nonScratchOrgs", "scratchOrgs"):
                    for entry in cli_result.get(org_list_key, []):
                        username = entry.get("username", "")
                        if username in known_usernames:
                            continue
                        orgs.append(
                            {
                                "alias": entry.get("alias") or None,
                                "username": username,
                                "connected_status": entry.get("connectedStatus", "Unknown"),
                                "instance_url": entry.get("instanceUrl"),
                            }
                        )
                        known_usernames.add(username)
            except Exception as exc:
                errors.append(f"sf CLI org list failed (non-fatal, env-var org still returned if available): {exc}")
        else:
            errors.append("sf CLI not installed — only the env-var-authenticated org is listed")

        if not orgs:
            return cls._format_error("; ".join(errors) or "No orgs available", error_type="SfAuthError")

        logger.info(f"[GITOPS] sf_list_orgs | {len(orgs)} org(s)")
        result = cls._format_success(orgs=orgs)
        if errors:
            result["warnings"] = errors
        return result
