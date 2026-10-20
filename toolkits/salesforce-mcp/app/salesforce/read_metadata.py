"""
Read Metadata Tool — look up an existing metadata component (CustomField,
ValidationRule, PermissionSet, Flow, ApexClass, ApexTrigger) by name via the
Tooling API, so an agent can check for conflicts/existing components before
creating one.
"""

from __future__ import annotations

import logging

from .base import SalesforceToolBase

logger = logging.getLogger(__name__)

# metadata_type -> Tooling sObject to query, the field holding its name, and the columns returned.
# Flow is looked up through FlowDefinition: the Flow sObject is one row per version and has no
# DeveloperName to filter on.
_SUPPORTED_METADATA_TYPES = {
    "CustomField": {"sobject": "CustomField", "filter_field": "DeveloperName", "columns": "Id, DeveloperName, TableEnumOrId, Metadata"},
    "ValidationRule": {"sobject": "ValidationRule", "filter_field": "ValidationName", "columns": "Id, ValidationName, Metadata"},
    "PermissionSet": {"sobject": "PermissionSet", "filter_field": "Name", "columns": "Id, Name, Metadata"},
    "Flow": {"sobject": "FlowDefinition", "filter_field": "DeveloperName", "columns": "Id, DeveloperName, ActiveVersionId, LatestVersionId"},
    "ApexClass": {"sobject": "ApexClass", "filter_field": "Name", "columns": "Id, Name, ApiVersion, Status, Body"},
    "ApexTrigger": {"sobject": "ApexTrigger", "filter_field": "Name", "columns": "Id, Name, TableEnumOrId, ApiVersion, Status, Body"},
}

SUPPORTED_TYPES = tuple(_SUPPORTED_METADATA_TYPES)


def _soql_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class ReadMetadataTool(SalesforceToolBase):
    """Read existing metadata to check for conflicts or existing components before creating."""

    name = "sf_read_metadata"
    description = "Read existing metadata to check for conflicts or existing components before creating."

    @classmethod
    def execute(cls, metadata_type: str, full_name: str) -> dict:
        """
        Look up a metadata component by its full name.

        Args:
            metadata_type: One of CustomField, ValidationRule, PermissionSet, Flow, ApexClass, ApexTrigger.
            full_name: The component's full name. For CustomField, use the
                "Object__c.Field__c" form (e.g. "Account.My_Field__c"); a bare
                name for every other type.

        Returns:
            dict with success flag and the found record(s), or
            found=False (not an error — this is the expected "no conflict"
            case) when nothing matches, or success=False + error on an
            unsupported type / API failure.
        """
        if metadata_type not in _SUPPORTED_METADATA_TYPES:
            return cls._format_error(
                f"Unsupported metadata_type {metadata_type!r}. Supported: {', '.join(SUPPORTED_TYPES)}",
                error_type="ValidationError",
            )
        if not full_name or not full_name.strip():
            return cls._format_error("full_name is required", error_type="ValidationError")

        full_name = full_name.strip()
        spec = _SUPPORTED_METADATA_TYPES[metadata_type]

        try:
            if metadata_type == "CustomField":
                if "." not in full_name:
                    return cls._format_error(
                        "CustomField full_name must be 'Object__c.Field__c'",
                        error_type="ValidationError",
                    )
                object_name, field_name = full_name.split(".", 1)
                if field_name.endswith("__c"):
                    field_name = field_name[: -len("__c")]
                soql = (
                    f"SELECT {spec['columns']} FROM CustomField "
                    f"WHERE DeveloperName = '{_soql_literal(field_name)}' AND TableEnumOrId = '{_soql_literal(object_name)}'"
                )
            else:
                soql = (
                    f"SELECT {spec['columns']} FROM {spec['sobject']} "
                    f"WHERE {spec['filter_field']} = '{_soql_literal(full_name)}'"
                )

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
