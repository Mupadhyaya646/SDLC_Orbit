"""
Read Metadata Tool — look up an existing metadata component (CustomField,
ValidationRule, PermissionSet, Flow) by name via the Tooling API, so an
agent can check for conflicts/existing components before creating one.
"""

from __future__ import annotations

import logging

from .base import SalesforceToolBase

logger = logging.getLogger(__name__)

# Tooling API sObject name -> the field holding its "full name" for lookup,
# and whether that full name is "Object__c.Field__c" (needs splitting into
# a TableEnumOrId filter) or a flat DeveloperName.
_SUPPORTED_METADATA_TYPES = {
    "CustomField": {"filter_field": "DeveloperName", "composite_name": True},
    "ValidationRule": {"filter_field": "ValidationName", "composite_name": False},
    "PermissionSet": {"filter_field": "Name", "composite_name": False},
    "Flow": {"filter_field": "DeveloperName", "composite_name": False},
}


class ReadMetadataTool(SalesforceToolBase):
    """Read existing metadata to check for conflicts or existing components before creating."""

    name = "sf_read_metadata"
    description = "Read existing metadata to check for conflicts or existing components before creating."

    @classmethod
    def execute(cls, metadata_type: str, full_name: str) -> dict:
        """
        Look up a metadata component by its full name.

        Args:
            metadata_type: One of CustomField, ValidationRule, PermissionSet, Flow.
            full_name: The component's full name. For CustomField, use the
                "Object__c.Field__c" form (e.g. "Account.My_Field__c").

        Returns:
            dict with success flag and the found record(s), or
            found=False (not an error — this is the expected "no conflict"
            case) when nothing matches, or success=False + error on an
            unsupported type / API failure.
        """
        if metadata_type not in _SUPPORTED_METADATA_TYPES:
            return cls._format_error(
                f"Unsupported metadata_type {metadata_type!r}. Supported: "
                f"{', '.join(_SUPPORTED_METADATA_TYPES)}",
                error_type="ValidationError",
            )
        if not full_name or not full_name.strip():
            return cls._format_error("full_name is required", error_type="ValidationError")

        full_name = full_name.strip()
        spec = _SUPPORTED_METADATA_TYPES[metadata_type]

        try:
            if metadata_type == "CustomField" and spec["composite_name"]:
                if "." not in full_name:
                    return cls._format_error(
                        "CustomField full_name must be 'Object__c.Field__c'",
                        error_type="ValidationError",
                    )
                object_name, field_name = full_name.split(".", 1)
                soql = (
                    f"SELECT Id, DeveloperName, TableEnumOrId, Metadata "
                    f"FROM CustomField WHERE DeveloperName = '{field_name}' "
                    f"AND TableEnumOrId = '{object_name}'"
                )
            else:
                filter_field = spec["filter_field"]
                soql = f"SELECT Id, {filter_field}, Metadata FROM {metadata_type} WHERE {filter_field} = '{full_name}'"

            records = cls._tooling_query(soql)
        except Exception as exc:
            return cls._format_error(f"Could not query {metadata_type} {full_name}: {exc}")

        if not records:
            return cls._format_success(
                metadata_type=metadata_type,
                full_name=full_name,
                found=False,
                record=None,
            )

        return cls._format_success(
            metadata_type=metadata_type,
            full_name=full_name,
            found=True,
            record=records[0],
            total_matches=len(records),
        )
