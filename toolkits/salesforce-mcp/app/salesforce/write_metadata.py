"""
Write Metadata Tool — create or update a single metadata component
(CustomField, ValidationRule, PermissionSet, Flow, ApexClass, ApexTrigger)
via the Tooling API's REST interface.

Accepts the component definition as a JSON object matching the Tooling
API's REST sObject shape (NOT raw Metadata API XML) — this is a deliberate
simplification: the Tooling API lets us POST/PATCH a single component as
plain JSON instead of building a full Metadata API deploy ZIP, which is
far simpler to implement correctly for one-component-at-a-time admin/dev
work. See sf_deploy_metadata for the multi-component batch case.

Per-type behaviour:
  * CustomField / ValidationRule / PermissionSet — POST to create, PATCH the
    existing record to update.
  * Flow — always POSTs a new Flow version (Flow records are immutable per
    version; Salesforce creates the FlowDefinition on the first one). Set
    Metadata.status to "Active" to activate the new version.
  * ApexClass / ApexTrigger — the source goes in "Body" (ApexTrigger also
    needs "TableEnumOrId", e.g. "Account"). New components are POSTed;
    existing ones are recompiled through a MetadataContainer +
    ContainerAsyncRequest, which is the Tooling API's supported way to edit
    Apex and returns compile errors. Apex can only be written this way in
    sandbox / developer / scratch orgs — production needs a Metadata API
    deploy with tests (sf_deploy_validate / the devops agent).
"""

from __future__ import annotations

import logging
import time

from .base import SalesforceToolBase
from .read_metadata import ReadMetadataTool

logger = logging.getLogger(__name__)

# Tooling API sObject name for each metadata_type we support creating.
_TOOLING_SOBJECT = {
    "CustomField": "CustomField",
    "ValidationRule": "ValidationRule",
    "PermissionSet": "PermissionSet",
    "Flow": "Flow",
    "ApexClass": "ApexClass",
    "ApexTrigger": "ApexTrigger",
}

_APEX_TYPES = {"ApexClass": "ApexClassMember", "ApexTrigger": "ApexTriggerMember"}
_APEX_POLL_SECONDS = 2
_APEX_POLL_ATTEMPTS = 60


class WriteMetadataTool(SalesforceToolBase):
    """Create/update metadata (fields, validation rules, flows, permission
    sets, Apex classes, Apex triggers) in the connected org."""

    name = "sf_write_metadata"
    description = (
        "Create/update metadata (fields, validation rules, flows, permission sets, "
        "Apex classes, Apex triggers) in the connected org."
    )

    @classmethod
    def execute(cls, metadata_type: str, full_name: str, metadata_json: dict) -> dict:
        """
        Create a new metadata component, or update it if one with the same
        full_name already exists (checked via ReadMetadataTool first).

        Args:
            metadata_type: One of CustomField, ValidationRule, PermissionSet,
                Flow, ApexClass, ApexTrigger.
            full_name: The component's intended full name (e.g.
                "Account.My_Field__c" for a CustomField, "AccountService" for
                an ApexClass).
            metadata_json: The Tooling API REST body for this component —
                e.g. for a CustomField: {"Metadata": {"label": "My Field",
                "type": "Text", "length": 80}}; for an ApexClass:
                {"Body": "public with sharing class AccountService { ... }"};
                for an ApexTrigger: {"TableEnumOrId": "Account",
                "Body": "trigger AccountTrigger on Account (before insert) { ... }"};
                for a Flow: {"Metadata": {<Flow metadata>, "status": "Active"}}.

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
        if metadata_type in _APEX_TYPES:
            return cls._write_apex(metadata_type, full_name, metadata_json)

        sobject = _TOOLING_SOBJECT[metadata_type]
        body = {**metadata_json, "FullName": full_name}

        try:
            if metadata_type == "Flow":
                result = cls._tooling_post("sobjects/Flow", body)
                return cls._format_success(
                    metadata_type=metadata_type, full_name=full_name, action="created_version", id=result.get("id")
                )

            existing = ReadMetadataTool.execute(metadata_type=metadata_type, full_name=full_name)
        except Exception as exc:
            return cls._format_error(f"Could not write {metadata_type} {full_name}: {exc}")

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

    @classmethod
    def _write_apex(cls, metadata_type: str, full_name: str, metadata_json: dict) -> dict:
        source = metadata_json.get("Body")
        if not isinstance(source, str) or not source.strip():
            return cls._format_error(f"{metadata_type} needs the Apex source in metadata_json.Body", error_type="ValidationError")
        if metadata_type == "ApexTrigger" and not metadata_json.get("TableEnumOrId"):
            return cls._format_error("ApexTrigger needs metadata_json.TableEnumOrId (e.g. 'Account')", error_type="ValidationError")

        try:
            existing = ReadMetadataTool.execute(metadata_type=metadata_type, full_name=full_name)
            if not existing.get("success"):
                return existing
            if not existing.get("found"):
                body = {"Body": source}
                if metadata_type == "ApexTrigger":
                    body["TableEnumOrId"] = metadata_json["TableEnumOrId"]
                if metadata_json.get("ApiVersion"):
                    body["ApiVersion"] = metadata_json["ApiVersion"]
                result = cls._tooling_post(f"sobjects/{metadata_type}", body)
                return cls._format_success(metadata_type=metadata_type, full_name=full_name, action="created", id=result.get("id"))

            existing_id = existing["record"]["Id"]
            cls._compile_in_container(metadata_type, full_name, existing_id, source)
            return cls._format_success(metadata_type=metadata_type, full_name=full_name, action="updated", id=existing_id)
        except Exception as exc:
            return cls._format_error(f"Could not write {metadata_type} {full_name}: {exc}")

    @classmethod
    def _compile_in_container(cls, metadata_type: str, full_name: str, entity_id: str, source: str) -> None:
        """Save new source for an existing Apex class/trigger; raises with the compile errors on failure."""
        container = cls._tooling_post("sobjects/MetadataContainer", {"Name": f"orbit-{full_name}-{int(time.time())}"[:32]})
        container_id = container["id"]
        try:
            cls._tooling_post(
                f"sobjects/{_APEX_TYPES[metadata_type]}",
                {"MetadataContainerId": container_id, "ContentEntityId": entity_id, "Body": source},
            )
            request = cls._tooling_post(
                "sobjects/ContainerAsyncRequest", {"MetadataContainerId": container_id, "IsCheckOnly": False}
            )
            for _ in range(_APEX_POLL_ATTEMPTS):
                status = cls._tooling_get(f"sobjects/ContainerAsyncRequest/{request['id']}")
                state = status.get("State")
                if state == "Completed":
                    return
                if state in ("Failed", "Error", "Aborted", "Invalidated"):
                    raise Exception(f"compile {state}: {status.get('DeployDetails') or status.get('ErrorMsg')}")
                time.sleep(_APEX_POLL_SECONDS)
            raise Exception("timed out waiting for the Apex compile")
        finally:
            try:
                cls._request("DELETE", cls._tooling_url, f"sobjects/MetadataContainer/{container_id}")
            except Exception:
                logger.warning("[SF] could not delete MetadataContainer %s", container_id)
