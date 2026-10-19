"""
Deploy Validate Tool — check-only deploy for larger, manifest-based change
sets (sf_deploy_metadata's 10-component Tooling-API-loop is for small
declarative batches; this is for everything else: Apex classes/triggers,
LWC bundles, multi-component manifests).

Implementation choice: shells out to the `sf` CLI (`sf project deploy
validate`), NOT a hand-rolled Metadata API SOAP deploy() call — the SOAP
deploy/checkDeployStatus polling loop, ZIP packaging, and package.xml
generation that a correct from-scratch implementation needs is
substantial, and the `sf` CLI already does all of this correctly. This is
a documented limitation, not an oversight: **the `sf` CLI must be
installed in this toolkit's Dockerfile** (it is — see Dockerfile's
`npm install -g @salesforce/cli` step) and this tool authenticates it
per-request via `sf org login access-token --instance-url <url>
--no-prompt`, feeding it the same OAuth2 access token SalesforceToolBase
already obtained — no separate `sf`-specific credential needed.

Caller must supply the component files to validate as a flat dict of
{relative_path: file_content}, written to a temp SFDX-shaped directory
before `sf project deploy validate` runs against it.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile

from .base import SalesforceToolBase

logger = logging.getLogger(__name__)

_SF_CLI_TIMEOUT_SECONDS = 180


class DeployValidateTool(SalesforceToolBase):
    """Validate-only deploy (check-only), used for larger manifest-based
    deploys and multi-component changes beyond sf_deploy_metadata's 10-component limit."""

    name = "sf_deploy_validate"
    description = (
        "Validate-only deploy (check-only), used for larger manifest-based deploys."
    )

    @classmethod
    def execute(
        cls,
        source_files: dict[str, str],
        test_level: str = "NoTestRun",
        test_classes: list[str] | None = None,
    ) -> dict:
        """
        Run `sf project deploy validate` (checkOnly=true) against the given
        source files.

        Args:
            source_files: {relative_path: file_content} — paths relative to
                an sfdx project root, e.g. {"force-app/main/default/classes/
                Foo.cls": "public class Foo {...}", "force-app/main/default/
                classes/Foo.cls-meta.xml": "<?xml ...?>"}. Caller (the
                devops agent, or github-commit's gitops toolkit) is
                responsible for providing valid SFDX-shaped file content.
            test_level: One of NoTestRun, RunSpecifiedTests, RunLocalTests,
                RunAllTestsInOrg.
            test_classes: Required if test_level == "RunSpecifiedTests".

        Returns:
            dict with success flag, numComponentErrors/numComponentsDeployed/
            numComponentsTotal and component-level errors on failure, or
            success=False + a raw CLI error message if the CLI itself failed
            to run (auth failure, CLI not installed, etc).
        """
        if not source_files or not isinstance(source_files, dict):
            return cls._format_error("source_files must be a non-empty dict", error_type="ValidationError")
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

        # Ensure we have a fresh OAuth2 token + instance_url before handing it to the CLI.
        cls._ensure_auth()
        from .base import _token_cache  # local import to read the module-level cache

        project_dir = tempfile.mkdtemp(prefix="sf_deploy_validate_")
        try:
            for rel_path, content in source_files.items():
                abs_path = os.path.join(project_dir, rel_path)
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                with open(abs_path, "w", encoding="utf-8") as f:
                    f.write(content)

            # Minimal sfdx-project.json so `sf project deploy validate` recognizes the directory.
            with open(os.path.join(project_dir, "sfdx-project.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "packageDirectories": [{"path": "force-app", "default": True}],
                        "sourceApiVersion": cls._api_version(),
                    },
                    f,
                )

            login_cmd = [
                "sf", "org", "login", "access-token",
                "--instance-url", _token_cache["instance_url"],
                "--no-prompt",
                "--alias", "orbit-validate-target",
                "--json",
            ]
            login_result = subprocess.run(
                login_cmd,
                input=_token_cache["access_token"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=project_dir,
            )
            if login_result.returncode != 0:
                return cls._format_error(
                    f"sf CLI login failed: {login_result.stderr[:400] or login_result.stdout[:400]}",
                    error_type="SfCliError",
                )

            validate_cmd = [
                "sf", "project", "deploy", "validate",
                "--source-dir", "force-app",
                "--target-org", "orbit-validate-target",
                "--test-level", test_level,
                "--json",
            ]
            if test_level == "RunSpecifiedTests" and test_classes:
                validate_cmd += ["--tests", ",".join(test_classes)]

            result = subprocess.run(
                validate_cmd,
                capture_output=True,
                text=True,
                timeout=_SF_CLI_TIMEOUT_SECONDS,
                cwd=project_dir,
            )

            try:
                parsed = json.loads(result.stdout)
            except json.JSONDecodeError:
                return cls._format_error(
                    f"sf CLI returned non-JSON output: {result.stdout[:400] or result.stderr[:400]}",
                    error_type="SfCliError",
                )

            deploy_result = parsed.get("result", {})
            success = parsed.get("status") == 0 and deploy_result.get("success", False)

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
        except subprocess.TimeoutExpired:
            return cls._format_error("sf CLI validate timed out", error_type="SfCliError")
        except Exception as exc:
            return cls._format_error(f"Unexpected error running sf CLI validate: {exc}")
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)
