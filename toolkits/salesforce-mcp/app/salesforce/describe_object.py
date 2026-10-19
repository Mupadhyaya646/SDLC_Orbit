"""
Describe Object Tool — fetch field/relationship metadata for a Salesforce
sObject via the standard REST API's /describe endpoint.
"""

from __future__ import annotations

import logging

from .base import SalesforceToolBase

logger = logging.getLogger(__name__)


class DescribeObjectTool(SalesforceToolBase):
    """Describe an existing object's fields/relationships."""

    name = "sf_describe_object"
    description = "Describe an existing object's fields/relationships."

    @classmethod
    def execute(cls, object_name: str) -> dict:
        """
        Fetch the full describe for an sObject and return a flat,
        agent-friendly summary: fields (name/type/label/required/picklist
        values) and relationship fields (lookup/master-detail targets).

        Args:
            object_name: API name of the object, e.g. "Account" or "My_Object__c".

        Returns:
            dict with success flag, object metadata, or success=False + error.
        """
        if not object_name or not object_name.strip():
            return cls._format_error("object_name is required", error_type="ValidationError")

        object_name = object_name.strip()

        try:
            data = cls._rest_get(f"sobjects/{object_name}/describe")
        except Exception as exc:
            return cls._format_error(f"Could not describe object {object_name}: {exc}")

        fields = []
        relationships = []
        for f in data.get("fields", []):
            field_entry = {
                "name": f.get("name"),
                "label": f.get("label"),
                "type": f.get("type"),
                "required": (not f.get("nillable", True)) and not f.get("defaultedOnCreate", False),
                "custom": f.get("custom", False),
            }
            if f.get("type") == "picklist":
                field_entry["picklist_values"] = [
                    pv.get("value") for pv in f.get("picklistValues", []) if pv.get("active")
                ]
            fields.append(field_entry)

            if f.get("type") in ("reference",) and f.get("referenceTo"):
                relationships.append({
                    "field": f.get("name"),
                    "relationship_name": f.get("relationshipName"),
                    "reference_to": f.get("referenceTo"),
                })

        return cls._format_success(
            object_name=object_name,
            label=data.get("label"),
            label_plural=data.get("labelPlural"),
            custom=data.get("custom", False),
            createable=data.get("createable", False),
            updateable=data.get("updateable", False),
            fields=fields,
            relationships=relationships,
            total_fields=len(fields),
        )
