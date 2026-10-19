from dotenv import load_dotenv
load_dotenv()

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
import json
import time
import signal
import sys
import threading
import os
import logging

# Try to fix the path if running in containerized environment
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

basic_logger = logging.getLogger(__name__)

try:
    from app.logger import (
        get_logger,
        log_server_startup,
        log_server_ready,
        log_server_shutdown,
        log_request_metrics,
        log_server_health,
        create_server_stats,
    )
    basic_logger.info("✓ Successfully imported from app.logger")
except ModuleNotFoundError as e:
    basic_logger.error(f"✗ FAILED to import app.logger: {e}")
    raise

try:
    from app.middleware import setup_uvicorn_logging
    basic_logger.info("✓ Successfully imported from app.middleware")
except ModuleNotFoundError as e:
    basic_logger.error(f"✗ FAILED to import app.middleware: {e}")
    raise

try:
    from app.salesforce import (
        DescribeObjectTool,
        ReadMetadataTool,
        WriteMetadataTool,
        DeployMetadataTool,
        DeployValidateTool,
    )
    from app.salesforce.base import SalesforceToolBase
    basic_logger.info("✓ Successfully imported from app.salesforce")
except ModuleNotFoundError as e:
    basic_logger.error(f"✗ FAILED to import app.salesforce: {e}")
    raise

# Server configuration — PORT must match deploy-salesforce-mcp.yaml's
# containerPort (6000) and the PORT env var it sets.
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "6000"))
mcp = FastMCP("Salesforce MCP Server", host=HOST, port=PORT)

logger = get_logger(__name__)
server_stats = create_server_stats()


def setup_signal_handlers():
    def signal_handler(sig, frame):
        logger.info(f"🛑 Received signal {sig}")
        log_server_shutdown(logger)
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


# ---------------------------------------------------------------------------
# Plain HTTP /healthz route for k8s liveness/readiness probes.
#
# deploy-salesforce-mcp.yaml's probes hit `GET /healthz` over plain HTTP, not
# an MCP tool call (unlike the Jira reference server, which only exposes a
# `health_check` MCP *tool* — insufficient here since FastMCP's
# streamable-http transport doesn't itself answer bare HTTP GETs on an
# arbitrary path). FastMCP's @mcp.custom_route() mounts an extra Starlette
# route alongside the MCP ASGI app for exactly this case. If a future `mcp`
# package version renames/removes custom_route, pin the working version in
# requirements.txt rather than silently losing the k8s probe target.
# ---------------------------------------------------------------------------
@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "uptime_seconds": round(time.time() - server_stats["start_time"], 2)})


@mcp.tool()
def health_check() -> str:
    """Health check tool for MCP-level monitoring (mirrors /healthz but callable as a tool)."""
    try:
        uptime = time.time() - server_stats["start_time"]
        health_data = {
            "status": "healthy",
            "uptime_seconds": round(uptime, 2),
            "total_requests": server_stats["total_requests"],
            "success_rate": round(
                (server_stats["successful_requests"] / max(server_stats["total_requests"], 1)) * 100, 2
            ),
            "timestamp": time.time(),
        }
        return json.dumps(health_data)
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return json.dumps({"status": "unhealthy", "error": str(e)})


# ============= sf_describe_object =============

@mcp.tool()
def sf_describe_object(object_name: str = "") -> str:
    """
    Describe an existing object's fields/relationships.

    Args:
        object_name: API name of the sObject, e.g. "Account" or "My_Object__c". Required.

    Returns:
        JSON string with success flag, object label/createable/updateable,
        fields (name/label/type/required/custom/picklist_values), and
        relationships (lookup/master-detail fields with reference_to).
    """
    start_time = time.time()
    tool_name = "sf_describe_object"
    try:
        logger.info(f"🔧 TOOL_START | {tool_name} | {object_name}")
        if not object_name:
            raise Exception("object_name is required")
        env_check = SalesforceToolBase.validate_env_vars()
        if not env_check["success"]:
            raise Exception(env_check["error"])

        result = DescribeObjectTool.execute(object_name=object_name)

        duration = time.time() - start_time
        log_request_metrics(logger, server_stats, tool_name, result.get("success", False), duration)
        return json.dumps(result)
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"🚨 TOOL_ERROR | {tool_name} | Error: {str(e)}")
        log_request_metrics(logger, server_stats, tool_name, False, duration)
        return json.dumps({"success": False, "error": str(e)})


# ============= sf_read_metadata =============

@mcp.tool()
def sf_read_metadata(metadata_type: str = "", full_name: str = "") -> str:
    """
    Read existing metadata to check for conflicts or existing components before creating.

    Args:
        metadata_type: One of CustomField, ValidationRule, PermissionSet, Flow. Required.
        full_name: The component's full name (e.g. "Account.My_Field__c" for
            a CustomField; a bare name for ValidationRule/PermissionSet/Flow). Required.

    Returns:
        JSON string with success flag, found (bool), and the record if found.
    """
    start_time = time.time()
    tool_name = "sf_read_metadata"
    try:
        logger.info(f"🔧 TOOL_START | {tool_name} | {metadata_type} | {full_name}")
        if not metadata_type or not full_name:
            raise Exception("metadata_type and full_name are required")
        env_check = SalesforceToolBase.validate_env_vars()
        if not env_check["success"]:
            raise Exception(env_check["error"])

        result = ReadMetadataTool.execute(metadata_type=metadata_type, full_name=full_name)

        duration = time.time() - start_time
        log_request_metrics(logger, server_stats, tool_name, result.get("success", False), duration)
        return json.dumps(result)
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"🚨 TOOL_ERROR | {tool_name} | Error: {str(e)}")
        log_request_metrics(logger, server_stats, tool_name, False, duration)
        return json.dumps({"success": False, "error": str(e)})


# ============= sf_write_metadata =============

@mcp.tool()
def sf_write_metadata(metadata_type: str = "", full_name: str = "", metadata_json: str = "") -> str:
    """
    Create/update declarative metadata (objects, fields, validation rules,
    flows, permission sets, layouts) in the SFDX workspace.

    Args:
        metadata_type: One of CustomField, ValidationRule, PermissionSet, Flow. Required.
        full_name: The component's intended full name (e.g. "Account.My_Field__c"). Required.
        metadata_json: JSON string of the Tooling API REST body for this
            component, e.g. '{"Metadata": {"label": "My Field", "type":
            "Text", "length": 80}}'. FullName is set automatically from the
            full_name argument. Required.

    Returns:
        JSON string with success flag, action ("created"|"updated"), and id.
    """
    start_time = time.time()
    tool_name = "sf_write_metadata"
    try:
        logger.info(f"🔧 TOOL_START | {tool_name} | {metadata_type} | {full_name}")
        if not metadata_type or not full_name or not metadata_json:
            raise Exception("metadata_type, full_name, and metadata_json are required")
        env_check = SalesforceToolBase.validate_env_vars()
        if not env_check["success"]:
            raise Exception(env_check["error"])

        parsed_metadata = json.loads(metadata_json) if metadata_json else {}
        if not isinstance(parsed_metadata, dict):
            raise ValueError("metadata_json must be a JSON object")

        result = WriteMetadataTool.execute(
            metadata_type=metadata_type, full_name=full_name, metadata_json=parsed_metadata
        )

        duration = time.time() - start_time
        log_request_metrics(logger, server_stats, tool_name, result.get("success", False), duration)
        return json.dumps(result)
    except json.JSONDecodeError as e:
        duration = time.time() - start_time
        logger.error(f"🚨 TOOL_ERROR | {tool_name} | Invalid JSON in metadata_json: {str(e)}")
        log_request_metrics(logger, server_stats, tool_name, False, duration)
        return json.dumps({"success": False, "error": f"Invalid JSON in metadata_json: {str(e)}"})
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"🚨 TOOL_ERROR | {tool_name} | Error: {str(e)}")
        log_request_metrics(logger, server_stats, tool_name, False, duration)
        return json.dumps({"success": False, "error": str(e)})


# ============= sf_deploy_metadata =============

@mcp.tool()
def sf_deploy_metadata(components: str = "") -> str:
    """
    Deploy up to 10 components directly via Salesforce MCP-equivalent deploy calls.

    Args:
        components: JSON array string, each element shaped like
            {"metadata_type": "CustomField", "full_name": "...",
             "metadata_json": {...}} — same fields sf_write_metadata takes.
            Max 10 components per call. Required.

    Returns:
        JSON string with success flag (True only if ALL components
        succeeded), per-component results, succeeded_count, failed_count.
    """
    start_time = time.time()
    tool_name = "sf_deploy_metadata"
    try:
        logger.info(f"🔧 TOOL_START | {tool_name}")
        if not components:
            raise Exception("components is required")
        env_check = SalesforceToolBase.validate_env_vars()
        if not env_check["success"]:
            raise Exception(env_check["error"])

        parsed_components = json.loads(components) if components else []
        if not isinstance(parsed_components, list):
            raise ValueError("components must be a JSON array")

        result = DeployMetadataTool.execute(components=parsed_components)

        duration = time.time() - start_time
        log_request_metrics(logger, server_stats, tool_name, result.get("success", False), duration)
        return json.dumps(result)
    except json.JSONDecodeError as e:
        duration = time.time() - start_time
        logger.error(f"🚨 TOOL_ERROR | {tool_name} | Invalid JSON in components: {str(e)}")
        log_request_metrics(logger, server_stats, tool_name, False, duration)
        return json.dumps({"success": False, "error": f"Invalid JSON in components: {str(e)}"})
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"🚨 TOOL_ERROR | {tool_name} | Error: {str(e)}")
        log_request_metrics(logger, server_stats, tool_name, False, duration)
        return json.dumps({"success": False, "error": str(e)})


# ============= sf_deploy_validate =============

@mcp.tool()
def sf_deploy_validate(source_files: str = "", test_level: str = "NoTestRun", test_classes: str = "") -> str:
    """
    Validate-only deploy (check-only), used for larger manifest-based
    deploys and multi-component changes beyond sf_deploy_metadata's
    10-component limit (Apex classes/triggers, LWC bundles, etc).

    Args:
        source_files: JSON object string of {relative_path: file_content}
            pairs, paths relative to an sfdx project root (e.g.
            "force-app/main/default/classes/Foo.cls"). Required.
        test_level: One of NoTestRun, RunSpecifiedTests, RunLocalTests,
            RunAllTestsInOrg. Defaults to NoTestRun.
        test_classes: Comma-separated test class names. Required if
            test_level is RunSpecifiedTests.

    Returns:
        JSON string with success flag, numComponentsTotal/Errors,
        numTestsTotal/Errors, component_errors, test_errors. success=False
        with error_type "EnvironmentError" if the `sf` CLI isn't installed.
    """
    start_time = time.time()
    tool_name = "sf_deploy_validate"
    try:
        logger.info(f"🔧 TOOL_START | {tool_name} | test_level={test_level}")
        if not source_files:
            raise Exception("source_files is required")
        env_check = SalesforceToolBase.validate_env_vars()
        if not env_check["success"]:
            raise Exception(env_check["error"])

        parsed_source_files = json.loads(source_files) if source_files else {}
        if not isinstance(parsed_source_files, dict):
            raise ValueError("source_files must be a JSON object")

        parsed_test_classes = [t.strip() for t in test_classes.split(",") if t.strip()] or None

        result = DeployValidateTool.execute(
            source_files=parsed_source_files,
            test_level=test_level,
            test_classes=parsed_test_classes,
        )

        duration = time.time() - start_time
        log_request_metrics(logger, server_stats, tool_name, result.get("success", False), duration)
        return json.dumps(result)
    except json.JSONDecodeError as e:
        duration = time.time() - start_time
        logger.error(f"🚨 TOOL_ERROR | {tool_name} | Invalid JSON in source_files: {str(e)}")
        log_request_metrics(logger, server_stats, tool_name, False, duration)
        return json.dumps({"success": False, "error": f"Invalid JSON in source_files: {str(e)}"})
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"🚨 TOOL_ERROR | {tool_name} | Error: {str(e)}")
        log_request_metrics(logger, server_stats, tool_name, False, duration)
        return json.dumps({"success": False, "error": str(e)})


if __name__ == "__main__":
    try:
        setup_uvicorn_logging()
        setup_signal_handlers()

        log_server_startup(logger, HOST, PORT)

        def periodic_health_log():
            time.sleep(60)
            while True:
                log_server_health(logger, server_stats)
                time.sleep(300)

        health_thread = threading.Thread(target=periodic_health_log, daemon=True)
        health_thread.start()

        log_server_ready(logger)
        logger.info("🌐 Starting MCP server with streamable-http transport")
        logger.info(f"💡 Health probe: GET /healthz on port {PORT}")

        mcp.run(transport="streamable-http")

    except Exception as e:
        logger.error(f"🚨 FATAL ERROR - Server failed to start: {e}")
        sys.exit(1)
    finally:
        log_server_shutdown(logger)
