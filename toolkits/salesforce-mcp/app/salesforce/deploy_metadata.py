"""
Deploy Metadata Tool — deploy up to 10 declarative components in one call
by looping WriteMetadataTool over each. A real Metadata API deploy()
(SOAP, ZIP-based) would give atomicity across components, but for a small
batch of declarative admin/dev changes a per-component Tooling API loop is
far simpler to implement correctly and is the deliberate choice here —
matches the plan's own framing ("deploy up to 10 components directly...
else fall back to the SF CLI for larger manifest-based deploys", which is
what sf_deploy_validate is for).
"""

from __future__ import annotations

import logging

from .base import SalesforceToolBase
from .write_metadata import WriteMetadataTool

logger = logging.getLogger(__name__)

_MAX_COMPONENTS = 10


class DeployMetadataTool(SalesforceToolBase):
    """Deploy up to 10 components directly via Salesforce MCP-equivalent deploy calls."""

    name = "sf_deploy_metadata"
    description = "Deploy up to 10 components directly via Salesforce MCP-equivalent deploy calls."

    @classmethod
    def execute(cls, components: list[dict]) -> dict:
        """
        Deploy a small batch of metadata components, one Tooling API call
        per component (NOT atomic — a failure partway through leaves
        earlier components already applied; the per-component result list
        tells the caller exactly which succeeded).

        Args:
            components: list of up to 10 dicts, each shaped like
                {"metadata_type": "CustomField", "full_name": "...",
                 "metadata_json": {...}} — same fields WriteMetadataTool takes.

        Returns:
            dict with success flag (True only if ALL components succeeded),
            results: list of per-component outcomes in input order,
            succeeded_count, failed_count.
        """
        if not isinstance(components, list) or not components:
            return cls._format_error("components must be a non-empty list", error_type="ValidationError")
        if len(components) > _MAX_COMPONENTS:
            return cls._format_error(
                f"Too many components ({len(components)}) — max {_MAX_COMPONENTS} per "
                f"sf_deploy_metadata call; use sf_deploy_validate for larger manifest-based deploys.",
                error_type="ValidationError",
            )

        results = []
        succeeded = 0
        for i, component in enumerate(components):
            metadata_type = component.get("metadata_type", "")
            full_name = component.get("full_name", "")
            metadata_json = component.get("metadata_json", {})

            try:
                result = WriteMetadataTool.execute(
                    metadata_type=metadata_type,
                    full_name=full_name,
                    metadata_json=metadata_json,
                )
            except Exception as exc:
                result = cls._format_error(f"Unhandled error deploying component {i}: {exc}")

            results.append({"index": i, "metadata_type": metadata_type, "full_name": full_name, **result})
            if result.get("success"):
                succeeded += 1

        all_succeeded = succeeded == len(components)
        return {
            "success": all_succeeded,
            "results": results,
            "succeeded_count": succeeded,
            "failed_count": len(components) - succeeded,
        }
