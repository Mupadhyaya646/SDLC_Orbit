"""
Write Metadata Tool — create or update a single declarative metadata
component (CustomField, ValidationRule, PermissionSet, Flow) via the
Tooling API's REST interface.

Accepts the component definition as a JSON object matching the Tooling
API's REST sObject shape (NOT raw Metadata API XML) — this is a deliberate
simplification: the Tooling API lets us POST/PATCH a single component as
plain JSON instead of building a full Metadata API deploy ZIP, which is
far simpler to implement correctly for one-component-at-a-time admin/dev
work. See sf_deploy_metadata for the multi-component batch case.
"""

from __future__ import annotations

import logging

from .base import SalesforceToolBase
from .read_metadata import ReadMetadataTool

logger = logging.getLogger(__name__)

# Tooling API sObject name for each metadata_type we support creating.
_TOOLING_SOBJECT = {
    "CustomField": "CustomField",
    "ValidationRule": "ValidationRule",
    "PermissionSet": "PermissionSet",
    "Flow": "FlowDefinition",
}


class WriteMetadataTool(SalesforceToolBase):
    """Create/update declarative metadata (objects, fields, validation rules,
    flows, permission sets, layouts) in the SFDX workspace."""

    name = "sf_write_metadata"
    description = (
        "Create/update declarative metadata (objects, fields, validation rules, "
        "flows, permission sets, layouts) in the SFDX workspace."
    )

    @classmethod
    def execute(cls, metadata_type: str, full_name: str, metadata_json: dict) -> dict:
        """
        Create a new metadata component, or update it if one with the same
        full_name already exists (checked via ReadMetadataTool first).

        Args:
            metadata_type: One of CustomField, ValidationRule, PermissionSet, Flow.
            full_name: The component's intended full name (e.g.
                "Account.My_Field__c" for a CustomField).
            metadata_json: The Tooling API REST body for this component —
                e.g. for a CustomField: {"FullName": "Account.My_Field__c",
                "Metadata": {"label": "My Field", "type": "Text", "length": 80}}.
                Caller is responsible for providing a shape the Tooling API
                accepts for the given metadata_type.

        Returns:
            dict with success flag, the created/updated component's Id and
            action ("created"|"updated"), or success=False + error.
        """
        if metadata_type not in _TOOLING_SOBJECT:
            return cls._format_error(
                f"Unsupported metadata_type {metadata_type!r}. Supported: "
                f"{', '.join(_TOOLING_SOBJECT)}",
                error_type="ValidationError",
            )
        if not full_name or not full_name.strip():
            return cls._format_error("full_name is required", error_type="ValidationError")
        if not isinstance(metadata_json, dict):
            return cls._format_error("metadata_json must be a JSON object", error_type="ValidationError")

        full_name = full_name.strip()
        sobject = _TOOLING_SOBJECT[metadata_type]
        body = {**metadata_json, "FullName": full_name}

        try:
            existing = ReadMetadataTool.execute(metadata_type=metadata_type, full_name=full_name)
        except Exception as exc:
            return cls._format_error(f"Could not check for existing {metadata_type} {full_name}: {exc}")

        try:
            if existing.get("success") and existing.get("found"):
                existing_id = existing["record"]["Id"]
                cls._tooling_patch(f"sobjects/{sobject}/{existing_id}", body)
                return cls._format_success(
                    metadata_type=metadata_type,
                    full_name=full_name,
                    action="updated",
                    id=existing_id,
                )

            result = cls._tooling_post(f"sobjects/{sobject}", body)
            return cls._format_success(
                metadata_type=metadata_type,
                full_name=full_name,
                action="created",
                id=result.get("id"),
            )
        except Exception as exc:
            return cls._format_error(f"Could not write {metadata_type} {full_name}: {exc}")
