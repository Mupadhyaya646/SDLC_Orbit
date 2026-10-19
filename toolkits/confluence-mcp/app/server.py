from dotenv import load_dotenv
load_dotenv()

from mcp.server.fastmcp import FastMCP
import anyio
import json
import time
import signal
import sys
import threading
import os
import logging

import uvicorn
from starlette.responses import JSONResponse
from starlette.routing import Route

# Try to fix the path if running in containerized environment
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Attempt to import app modules with error handling
# Using basic logger before app.logger is available
basic_logger = logging.getLogger(__name__)

try:
    from app.logger import (
        get_logger,
        log_server_startup,
        log_server_ready,
        log_server_shutdown,
        log_request_metrics,
        log_server_health,
        log_mcp_request,
        setup_mcp_logging,
        create_server_stats
    )
    basic_logger.info("✓ Successfully imported from app.logger")
except ModuleNotFoundError as e:
    basic_logger.error(f"✗ FAILED to import app.logger: {e}")
    basic_logger.error(f"  Error details: {type(e).__name__}: {str(e)}")
    raise

try:
    from app.middleware import setup_uvicorn_logging
    basic_logger.info("✓ Successfully imported from app.middleware")
except ModuleNotFoundError as e:
    basic_logger.error(f"✗ FAILED to import app.middleware: {e}")
    basic_logger.error(f"  Error details: {type(e).__name__}: {str(e)}")
    raise

try:
    from app.confluence import SearchContentTool, GetPageTool, UpdatePageTool, GetCurrentUserTool
    from app.confluence.base import ConfluenceToolBase
    basic_logger.info("✓ Successfully imported from app.confluence")
except ModuleNotFoundError as e:
    basic_logger.error(f"✗ FAILED to import app.confluence: {e}")
    basic_logger.error(f"  Error details: {type(e).__name__}: {str(e)}")
    raise

# Server configuration — PORT must match deploy-confluence-mcp.yaml's
# containerPort (6001) and its liveness/readiness probe port.
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "6001"))
mcp = FastMCP("Confluence MCP Server", host=HOST, port=PORT)

# Logger configs
logger = get_logger(__name__)

logger.info("=== PYTHON ENVIRONMENT DEBUG ===")
logger.info(f"Current Working Directory: {os.getcwd()}")
logger.debug(f"Python Path: {sys.path}")
logger.info(f"__file__: {__file__}")
logger.info(f"Script directory: {os.path.dirname(os.path.abspath(__file__))}")
logger.info(f"Added parent directory to sys.path: {parent_dir}")
logger.info("=====================================")

# Track server metrics
server_stats = create_server_stats()


def setup_signal_handlers():
    """Setup graceful shutdown handlers"""
    def signal_handler(sig, frame):
        logger.info(f"🛑 Received signal {sig}")
        log_server_shutdown(logger)
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


@mcp.tool()
def health_check() -> str:
    """
    Health check endpoint for monitoring systems (MCP tool form — see also
    the plain HTTP /healthz route added to the Starlette app below, which is
    what the k8s liveness/readiness probes actually hit).
    """
    try:
        logger.info("=== HEALTH CHECK TOOL INVOKED ===")
        uptime = time.time() - server_stats["start_time"]
        health_data = {
            "status": "healthy",
            "uptime_seconds": round(uptime, 2),
            "total_requests": server_stats["total_requests"],
            "success_rate": round((server_stats["successful_requests"] / max(server_stats["total_requests"], 1)) * 100, 2),
            "timestamp": time.time()
        }

        logger.debug(f"Health check requested - {health_data}")
        return json.dumps(health_data)

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return json.dumps({"status": "unhealthy", "error": str(e)})


# ============= Confluence Search Content Tool =============

@mcp.tool()
def search_content(query: str, space_key: str = "", limit: int = 10) -> str:
    """
    Search Confluence (CQL) for pages matching a free-text query, optionally
    scoped to a space.

    Args:
        query: Free text to search for. Required.
        space_key: Optional Confluence space key to scope the search to.
        limit: Maximum number of results to return (default 10).

    Returns:
        JSON string with success flag and a `results` list of
        {id, title, space_key, url, excerpt}; or success=False with error details.
    """
    start_time = time.time()
    tool_name = "search_content"

    try:
        logger.info(f"🔧 TOOL_START | {tool_name} | query={query[:60]!r} | space={space_key or '(any)'}")

        env_check = ConfluenceToolBase.validate_env_vars()
        if not env_check["success"]:
            raise Exception(env_check["error"])

        result = SearchContentTool.execute(
            query=query,
            space_key=space_key.strip() or None,
            limit=limit,
        )

        duration = time.time() - start_time
        log_request_metrics(logger, server_stats, tool_name, result.get("success", False), duration)
        return json.dumps(result)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"🚨 TOOL_ERROR | {tool_name} | Error: {str(e)}")
        log_request_metrics(logger, server_stats, tool_name, False, duration)
        return json.dumps({"success": False, "error": str(e)})


# ============= Confluence Get Page Tool =============

@mcp.tool()
def get_page(page_id: str, body_format: str = "storage") -> str:
    """
    Read a Confluence page's body (storage format) and version — real
    @devpuccino/mcp-confluence tool name.

    Args:
        page_id: Confluence page ID. Required.
        body_format: "storage" (default, Confluence storage-format XHTML) or "view".

    Returns:
        JSON string with success flag and {id, title, space_id, version, body, url};
        or success=False with error details.
    """
    start_time = time.time()
    tool_name = "get_page"

    try:
        logger.info(f"🔧 TOOL_START | {tool_name} | page_id={page_id}")

        env_check = ConfluenceToolBase.validate_env_vars()
        if not env_check["success"]:
            raise Exception(env_check["error"])

        result = GetPageTool.execute(page_id=page_id, body_format=body_format)

        duration = time.time() - start_time
        log_request_metrics(logger, server_stats, tool_name, result.get("success", False), duration)
        return json.dumps(result)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"🚨 TOOL_ERROR | {tool_name} | Error: {str(e)}")
        log_request_metrics(logger, server_stats, tool_name, False, duration)
        return json.dumps({"success": False, "error": str(e)})


# ============= Confluence Update Page Tool =============

@mcp.tool()
def update_page(page_id: str, new_body_storage: str, version_number: int, title: str = "") -> str:
    """
    Update an existing Confluence page (Change Log row append only) — real
    @devpuccino/mcp-confluence tool name.

    Args:
        page_id: Confluence page ID. Required.
        new_body_storage: The FULL new body, in Confluence storage-format XHTML.
            This replaces the entire body — construct the complete modified
            content (e.g. with the new <tr> inserted) before calling. Required.
        version_number: The page's CURRENT version number (from get_page). Required.
        title: Optional new title; current title is kept if omitted.

    Returns:
        JSON string with success flag and {id, version, url}; or success=False
        with error details.
    """
    start_time = time.time()
    tool_name = "update_page"

    try:
        logger.info(f"🔧 TOOL_START | {tool_name} | page_id={page_id} | version={version_number}")

        env_check = ConfluenceToolBase.validate_env_vars()
        if not env_check["success"]:
            raise Exception(env_check["error"])

        result = UpdatePageTool.execute(
            page_id=page_id,
            new_body_storage=new_body_storage,
            version_number=version_number,
            title=title.strip() or None,
        )

        duration = time.time() - start_time
        log_request_metrics(logger, server_stats, tool_name, result.get("success", False), duration)
        return json.dumps(result)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"🚨 TOOL_ERROR | {tool_name} | Error: {str(e)}")
        log_request_metrics(logger, server_stats, tool_name, False, duration)
        return json.dumps({"success": False, "error": str(e)})


# ============= Confluence Get Current User Tool =============

@mcp.tool()
def get_current_user() -> str:
    """
    Resolve the authenticated user's Confluence account ID for @mention
    rendering — real @devpuccino/mcp-confluence tool name.

    Returns:
        JSON string with success flag and {account_id, email, display_name,
        account_type, account_status}; or success=False with error details.
    """
    start_time = time.time()
    tool_name = "get_current_user"

    try:
        logger.info(f"🔧 TOOL_START | {tool_name}")

        env_check = ConfluenceToolBase.validate_env_vars()
        if not env_check["success"]:
            raise Exception(env_check["error"])

        result = GetCurrentUserTool.execute()

        duration = time.time() - start_time
        log_request_metrics(logger, server_stats, tool_name, result.get("success", False), duration)
        return json.dumps(result)

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"🚨 TOOL_ERROR | {tool_name} | Error: {str(e)}")
        log_request_metrics(logger, server_stats, tool_name, False, duration)
        return json.dumps({"success": False, "error": str(e)})


def setup_mcp_logging():
    """Setup MCP protocol logging hooks - simplified approach"""
    logger.info("🔍 MCP protocol logging enabled")


async def _healthz(request):
    """
    Plain HTTP health route for k8s liveness/readiness probes.

    FastMCP's `streamable_http_app()` only serves the MCP protocol itself —
    it has no plain HTTP health endpoint, and the `health_check` MCP *tool*
    above is only reachable via the MCP protocol, not a bare GET. Without
    this route, deploy-confluence-mcp.yaml's `httpGet: {path: /healthz}`
    probes would 404 and the pod would never go Ready. Confirmed-working
    pattern for extending FastMCP's underlying Starlette app: see the
    sibling lscai-connector toolkit's app/server.py, which adds middleware
    the same way (`starlette_app = mcp.streamable_http_app()` then mutate it
    before serving).
    """
    uptime = time.time() - server_stats["start_time"]
    return JSONResponse({"status": "ok", "uptime_seconds": round(uptime, 2)})


if __name__ == "__main__":
    try:
        setup_mcp_logging()
        setup_uvicorn_logging()
        setup_signal_handlers()

        log_server_startup(logger, HOST, PORT)

        print("=== RAW STDERR TEST ===", file=sys.__stderr__, flush=True)
        logger.info("Log before the server started running")

        def periodic_health_log():
            time.sleep(60)
            while True:
                log_server_health(logger, server_stats)
                time.sleep(300)

        health_thread = threading.Thread(target=periodic_health_log, daemon=True)
        health_thread.start()

        log_server_ready(logger)

        logger.info("🌐 Starting MCP server with streamable-http transport")
        logger.info("💡 TIP: Use the health_check tool to monitor server status")
        logger.info(f"🩺 Plain HTTP /healthz route added for k8s probes on port {PORT}")

        async def _serve():
            starlette_app = mcp.streamable_http_app()
            starlette_app.routes.append(Route("/healthz", _healthz, methods=["GET"]))
            config = uvicorn.Config(
                starlette_app,
                host=HOST,
                port=PORT,
                log_level="info",
            )
            server = uvicorn.Server(config)
            await server.serve()

        anyio.run(_serve)

    except Exception as e:
        logger.error(f"🚨 FATAL ERROR - Server failed to start: {e}")
        sys.exit(1)
    finally:
        log_server_shutdown(logger)
