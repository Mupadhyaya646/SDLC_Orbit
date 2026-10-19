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
    from app.gitops import (
        GitDiffTool,
        GitClassifyChangesTool,
        GitMirrorSfdxToMetadataTool,
        GitStageAndCommitTool,
        GitPushTool,
        GhCreatePrTool,
        SfListOrgsTool,
        SfDeployValidateTool,
    )
    from app.gitops.base import GitOpsToolBase
    basic_logger.info("✓ Successfully imported from app.gitops")
except ModuleNotFoundError as e:
    basic_logger.error(f"✗ FAILED to import app.gitops: {e}")
    raise

# Server configuration — PORT must match deploy-gitops-mcp.yaml's
# containerPort (6002) and the PORT env var it sets.
HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "6002"))
mcp = FastMCP("GitOps MCP Server", host=HOST, port=PORT)

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
# deploy-gitops-mcp.yaml's probes hit `GET /healthz` over plain HTTP, not
# an MCP tool call — same reasoning and same @mcp.custom_route() pattern
# as the sibling salesforce-mcp/confluence-mcp toolkit servers (the Jira
# reference server only exposes a `health_check` MCP *tool*, insufficient
# for a k8s HTTP probe).
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


def _run_tool(tool_name: str, fn, requires_github_env: bool = True):
    """Shared timing/logging/error-wrapping boilerplate for every tool below.

    requires_github_env=False for sf_list_orgs/sf_deploy_validate, which
    authenticate against Salesforce (their own env check inside
    list_orgs.py/deploy_validate.py), not GitHub — those two tools don't
    need the repo clone's GITHUB_TOKEN/GITHUB_REPO_URL to run.
    """
    start_time = time.time()
    try:
        logger.info(f"🔧 TOOL_START | {tool_name}")
        if requires_github_env:
            env_check = GitOpsToolBase.validate_env_vars()
            if not env_check["success"]:
                raise Exception(env_check["error"])
        result = fn()
        duration = time.time() - start_time
        log_request_metrics(logger, server_stats, tool_name, result.get("success", False), duration)
        return json.dumps(result)
    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"🚨 TOOL_ERROR | {tool_name} | Error: {str(e)}")
        log_request_metrics(logger, server_stats, tool_name, False, duration)
        return json.dumps({"success": False, "error": str(e)})


# ============= git_diff =============

@mcp.tool()
def git_diff(branch: str = "") -> str:
    """
    git status + content diff between force-app/main/default and src/,
    excluding objects/**.

    Args:
        branch: branch to sync the server's persistent clone to before
            diffing. Omit to diff whatever branch is currently checked out.

    Returns:
        JSON string with success flag, branch, and files: a list of
        {path, status} where status is "new"|"modified"|"deleted".
    """
    return _run_tool("git_diff", lambda: GitDiffTool.execute(branch=branch or None))


# ============= git_classify_changes =============

@mcp.tool()
def git_classify_changes(ai_authored_paths: str = "", branch: str = "") -> str:
    """
    Classify changed files as Claude-generated vs manual against session
    handoff records.

    Args:
        ai_authored_paths: JSON array string of force-app-relative paths
            the calling agent/orchestrator knows were AI-authored this
            session (sourced from its own pipeline handoff data — this
            tool has no database of its own to look this up from). Pass
            "[]" if there's no SESSION_ID / no recorded AI authorship —
            per the original design, that means ALL changes are manual.
            Required.
        branch: branch to diff against. Omit for the currently checked-out branch.

    Returns:
        JSON string with success flag, branch, claude_generated (list of
        {path, status}), manual (list of {path, status}).
    """
    def _execute():
        if not ai_authored_paths:
            raise ValueError("ai_authored_paths is required (pass \"[]\" for none)")
        parsed = json.loads(ai_authored_paths)
        if not isinstance(parsed, list):
            raise ValueError("ai_authored_paths must be a JSON array")
        return GitClassifyChangesTool.execute(ai_authored_paths=parsed, branch=branch or None)

    return _run_tool("git_classify_changes", _execute)


# ============= git_mirror_sfdx_to_metadata =============

@mcp.tool()
def git_mirror_sfdx_to_metadata(file_paths: str = "", branch: str = "") -> str:
    """
    Copy approved SFDX-layout files into Metadata API src/ layout (or
    delete on removal).

    Args:
        file_paths: JSON array string of force-app-relative paths to
            mirror (the subset the user approved at Gate 1/Gate 2), e.g.
            '["classes/Foo.cls", "classes/Foo.cls-meta.xml"]'. Required.
        branch: branch to sync the clone to first. Omit for the currently
            checked-out branch.

    Returns:
        JSON string with success flag, branch, mirrored (list of {path,
        action: "copied"|"deleted"}), skipped (list of {path, reason}).
    """
    def _execute():
        if not file_paths:
            raise ValueError("file_paths is required")
        parsed = json.loads(file_paths)
        if not isinstance(parsed, list):
            raise ValueError("file_paths must be a JSON array")
        return GitMirrorSfdxToMetadataTool.execute(file_paths=parsed, branch=branch or None)

    return _run_tool("git_mirror_sfdx_to_metadata", _execute)


# ============= git_stage_and_commit =============

@mcp.tool()
def git_stage_and_commit(paths: str = "", message: str = "", branch: str = "") -> str:
    """
    git add (explicit src/ paths only, never '.') and git commit with the
    approved message.

    Args:
        paths: JSON array string of explicit src/-relative paths to
            stage, e.g. '["src/classes/Foo.cls", "src/classes/Foo.cls-meta.xml"]'.
            Never pass "." or "-A"/"--all"/"*" — this tool rejects those. Required.
        message: the approved commit message. Required.
        branch: branch to sync the clone to first. Omit for the currently
            checked-out branch.

    Returns:
        JSON string with success flag, branch, commit_sha (short), staged.
    """
    def _execute():
        if not paths or not message:
            raise ValueError("paths and message are required")
        parsed = json.loads(paths)
        if not isinstance(parsed, list):
            raise ValueError("paths must be a JSON array")
        return GitStageAndCommitTool.execute(paths=parsed, message=message, branch=branch or None)

    return _run_tool("git_stage_and_commit", _execute)


# ============= git_push =============

@mcp.tool()
def git_push(branch: str = "") -> str:
    """
    git push to the current (non-protected) feature branch.

    Args:
        branch: branch to push. Omit to push whatever branch is currently
            checked out. Refuses with an error if the target branch is
            protected (default protected list: main,master — configurable
            via GITHUB_PROTECTED_BRANCHES).

    Returns:
        JSON string with success flag, branch, remote_url on success;
        success=False + error (including ProtectedBranchError) on failure.
    """
    return _run_tool("git_push", lambda: GitPushTool.execute(branch=branch or None))


# ============= gh_create_pr =============

@mcp.tool()
def gh_create_pr(title: str = "", body: str = "", base: str = "", head: str = "", reviewers: str = "", branch: str = "") -> str:
    """
    gh pr create with title/description/base/reviewers.

    Args:
        title: PR title. Required.
        body: PR description. Required.
        base: target branch the PR merges into (e.g. "main"). Required.
        head: source branch. Omit to use whatever branch is currently
            checked out.
        reviewers: comma-separated GitHub usernames (handles, not display
            names or emails).
        branch: branch to sync the clone to before running gh. Omit for
            the currently checked-out branch.

    Returns:
        JSON string with success flag, pr_url, pr_number on success.
    """
    def _execute():
        if not title or not base:
            raise ValueError("title and base are required")
        parsed_reviewers = [r.strip() for r in reviewers.split(",") if r.strip()] or None
        return GhCreatePrTool.execute(
            title=title, body=body, base=base, head=head or None, reviewers=parsed_reviewers, branch=branch or None
        )

    return _run_tool("gh_create_pr", _execute)


# ============= sf_list_orgs =============

@mcp.tool()
def sf_list_orgs() -> str:
    """
    Equivalent of `sf org list --all --json`, used to show the numbered
    target-org table at Gate 5 Step 2.

    Returns:
        JSON string with success flag, orgs: list of {alias, username,
        connected_status, instance_url}.
    """
    return _run_tool("sf_list_orgs", lambda: SfListOrgsTool.execute(), requires_github_env=False)


# ============= sf_deploy_validate =============

@mcp.tool()
def sf_deploy_validate(target_org: str = "", test_level: str = "NoTestRun", test_classes: str = "", branch: str = "") -> str:
    """
    Validate-only deploy against the user-selected target org for Gate 5,
    with sf-CLI-equivalent fallback semantics preserved in this prompt's
    Step 4a/4b logic.

    Args:
        target_org: the alias/username the user picked at Gate 5 Step 2. Required.
        test_level: One of NoTestRun, RunSpecifiedTests, RunLocalTests,
            RunAllTestsInOrg. Defaults to NoTestRun.
        test_classes: comma-separated test class names. Required if
            test_level is RunSpecifiedTests.
        branch: branch to sync the clone to before validating (the branch
            that was just pushed). Omit for the currently checked-out branch.

    Returns:
        JSON string with success flag, num_components_total/errors,
        num_tests_total/errors, component_errors, test_errors.
        error_type "SfAuthError" if target_org can't be authenticated —
        the agent must surface this to the user, never silently retry
        with a different org.
    """
    def _execute():
        if not target_org:
            raise ValueError("target_org is required")
        parsed_test_classes = [t.strip() for t in test_classes.split(",") if t.strip()] or None
        return SfDeployValidateTool.execute(
            target_org=target_org,
            test_level=test_level,
            test_classes=parsed_test_classes,
            branch=branch or None,
        )

    return _run_tool("sf_deploy_validate", _execute)


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
