"""
sf_deploy_validate — Gate 5's validate-only deploy against a user-selected
target org (sibling to salesforce-mcp-toolkit's own sf_deploy_validate,
but operating on the ALREADY-COMMITTED src/ tree in this server's
persistent clone, not on caller-supplied source_files — Gate 5 validates
what was just pushed, against a DIFFERENT downstream org than whatever
the main pipeline deployed to).

Implementation choice: shells out to the `sf` CLI (`sf project deploy
validate`), same approach and same documented rationale as the sibling
salesforce-mcp toolkit's deploy_validate.py — a hand-rolled Metadata API
SOAP deploy()/checkDeployStatus polling loop is substantial additional
work the `sf` CLI already does correctly. Reuses the SAME Salesforce
OAuth2 env vars as list_orgs.py in this same toolkit (see that module's
docstring) to authenticate the CLI non-interactively via `sf org login
access-token`.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess

from .base import GitOpsToolBase, METADATA_ROOT
from .list_orgs import SfListOrgsTool

logger = logging.getLogger(__name__)

_SF_CLI_TIMEOUT_SECONDS = 180


class SfDeployValidateTool(GitOpsToolBase):
    """Validate-only deploy against the user-selected target org for Gate 5, with sf-CLI-equivalent fallback semantics preserved in this prompt's Step 4a/4b logic."""

    name = "sf_deploy_validate"
    description = (
        "Validate-only deploy against the user-selected target org for Gate 5, "
        "with sf-CLI-equivalent fallback semantics preserved in this prompt's "
        "Step 4a/4b logic."
    )

    @classmethod
    def execute(
        cls,
        target_org: str,
        test_level: str = "NoTestRun",
        test_classes: list[str] | None = None,
        branch: str | None = None,
    ) -> dict:
        """
        Args:
            target_org: the alias or username the user picked at Gate 5
                Step 2 (from sf_list_orgs's output) — this is a DIFFERENT
                org than wherever the main pipeline already deployed to.
            test_level: One of NoTestRun, RunSpecifiedTests, RunLocalTests,
                RunAllTestsInOrg.
            test_classes: required if test_level == RunSpecifiedTests.
            branch: branch to sync the clone to before validating (the
                branch that was just pushed in git_push).

        Returns:
            dict with success flag, num_components_total/errors,
            num_tests_total/errors, component_errors, test_errors — same
            shape as the sibling salesforce-mcp toolkit's sf_deploy_validate,
            so github-commit-agent's Step 4/5 result-handling prompt text
            (written against that shape) works unchanged against this one.
            success=False + error_type "EnvironmentError" if the `sf` CLI
            isn't installed; error_type "SfAuthError" if target_org isn't
            a known/authenticated org (surfaced to the user per the
            original design's Step 5b — NEVER silently switched to a
            different org by this tool).
        """
        if not target_org or not target_org.strip():
            return cls._format_error("target_org is required", error_type="ValidationError")
        if test_level == "RunSpecifiedTests" and not test_classes:
            return cls._format_error(
                "test_classes is required when test_level is RunSpecifiedTests",
                error_type="ValidationError",
            )
        if shutil.which("sf") is None:
            return cls._format_error(
                "`sf` CLI is not installed in this container — see this toolkit's "
                "Dockerfile/README for the required `npm install -g @salesforce/cli` step.",
                error_type="EnvironmentError",
            )

        try:
            repo = cls.ensure_repo_cloned_and_synced(branch=branch)
        except Exception as exc:
            return cls._format_error(f"Could not sync repo clone: {exc}", error_type="RepoSyncError")

        metadata_root = repo / METADATA_ROOT
        if not metadata_root.exists():
            return cls._format_error(f"{METADATA_ROOT} does not exist in the clone", error_type="ValidationError")

        # Authenticate the `sf` CLI non-interactively against target_org.
        # This tool does NOT assume target_org is this server's own
        # env-var-authenticated org — it must be a pre-authenticated `sf`
        # CLI org (per sf_list_orgs's merged list) OR match this server's
        # own SF_USERNAME, in which case we authenticate it fresh via the
        # same OAuth2 flow sf_list_orgs uses.
        auth_result = cls._ensure_target_org_authenticated(target_org)
        if not auth_result["success"]:
            return auth_result

        validate_cmd = [
            "sf", "project", "deploy", "validate",
            "--source-dir", METADATA_ROOT,
            "--target-org", target_org,
            "--test-level", test_level,
            "--json",
        ]
        if test_level == "RunSpecifiedTests" and test_classes:
            validate_cmd += ["--tests", ",".join(test_classes)]

        try:
            result = subprocess.run(
                validate_cmd,
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=_SF_CLI_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return cls._format_error("sf CLI validate timed out", error_type="SfCliError")

        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            # Distinguish "org not found/auth error" (recoverable,
            # Salesforce-side) from true infra failure per the original
            # design's Step 4a/4b/Step 5b/Step 6 distinction — surfaced
            # via error_type so the agent's prompt logic can route
            # correctly instead of silently retrying with another org.
            stderr_lower = (result.stderr or "").lower()
            if "no org" in stderr_lower or "notfound" in stderr_lower or "invalid_login" in stderr_lower:
                return cls._format_error(
                    f"Target org issue: {result.stderr[:400] or result.stdout[:400]}",
                    error_type="SfAuthError",
                )
            return cls._format_error(
                f"sf CLI returned non-JSON output: {result.stdout[:400] or result.stderr[:400]}",
                error_type="SfCliError",
            )

        deploy_result = parsed.get("result", {})
        success = parsed.get("status") == 0 and deploy_result.get("success", False)

        logger.info(f"[GITOPS] sf_deploy_validate | target_org={target_org} | success={success}")
        return {
            "success": success,
            "status": deploy_result.get("status"),
            "num_components_total": deploy_result.get("numberComponentsTotal"),
            "num_components_errors": deploy_result.get("numberComponentErrors"),
            "num_tests_total": deploy_result.get("numberTestsTotal"),
            "num_tests_errors": deploy_result.get("numberTestErrors"),
            "component_errors": deploy_result.get("details", {}).get("componentFailures", []),
            "test_errors": deploy_result.get("details", {}).get("runTestResult", {}).get("failures", []),
        }

    @classmethod
    def _ensure_target_org_authenticated(cls, target_org: str) -> dict:
        """
        If target_org matches this server's own SF_USERNAME env var,
        authenticate it fresh via OAuth2 + `sf org login access-token`
        (same approach as the sibling salesforce-mcp toolkit's
        deploy_validate.py). Otherwise, assume it's already registered in
        the `sf` CLI's local auth store (per README: operators must run
        `sf org login web -a <alias>` once per target org as part of this
        server's operational setup — not automated here, since that flow
        is inherently interactive/browser-based for orgs this service
        account doesn't itself own).
        """
        env_sf_username = os.getenv("SF_USERNAME", "")
        if target_org != env_sf_username and target_org != os.getenv(f"SF_ALIAS_{target_org.upper()}", ""):
            # Not this server's own org — trust it's pre-authenticated.
            # `sf project deploy validate` will surface a clear
            # NamedOrgNotFound-style error if it isn't, which this
            # method's caller already classifies as SfAuthError.
            return {"success": True}

        try:
            token_data = SfListOrgsTool._authenticate_this_org()
        except Exception as exc:
            return cls._format_error(f"Could not authenticate {target_org}: {exc}", error_type="SfAuthError")

        login_cmd = [
            "sf", "org", "login", "access-token",
            "--instance-url", token_data["instance_url"],
            "--no-prompt",
            "--alias", target_org,
            "--json",
        ]
        result = subprocess.run(
            login_cmd,
            input=token_data["access_token"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return cls._format_error(
                f"sf CLI login failed for {target_org}: {result.stderr[:400] or result.stdout[:400]}",
                error_type="SfCliError",
            )
        return {"success": True}
