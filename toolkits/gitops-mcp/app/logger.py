import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import time
from datetime import datetime

LOGLEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR = "/tmp/app/logs"
LOG_FILE = os.path.join(LOG_DIR, "app.log")

def get_logger(name: str) -> logging.Logger:
    """
    Return logger with enhanced formatting for containerized environments.
    Uses sys.__stderr__ to bypass MCP hijacked stderr.
    """
    logger = logging.getLogger(name)

    # Avoid adding multiple handlers if logger already exists
    if logger.handlers:
        return logger
    os.makedirs(LOG_DIR, exist_ok=True)
    # Use original stderr to avoid stdio transport hijack
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # STDERR handler
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(LOGLEVEL)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    # File handler
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3)
    fh.setLevel(LOGLEVEL)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    logger.setLevel(LOGLEVEL)
    logger.propagate = False
    return logger


def log_server_startup(logger: logging.Logger, host: str, port: int):
    """Log server startup information"""
    logger.info("=" * 80)
    logger.info("🚀 GITOPS MCP SERVER STARTING")
    logger.info("=" * 80)
    logger.info(f"Server Host: {host}")
    logger.info(f"Server Port: {port}")
    logger.info(f"Log Level: {LOGLEVEL}")
    logger.info(f"Process ID: {os.getpid()}")
    logger.info(f"Python Version: {sys.version.split()[0]}")
    logger.info(f"Start Time: {datetime.now().isoformat()}")
    logger.info("=" * 80)

def log_server_ready(logger: logging.Logger):
    """Log when server is ready to accept connections"""
    logger.info("✅ SERVER READY - Accepting connections")
    logger.info("🔧 Available tools: git_diff, git_classify_changes, git_mirror_sfdx_to_metadata, "
                 "git_stage_and_commit, git_push, gh_create_pr, sf_list_orgs, sf_deploy_validate")

def log_server_shutdown(logger: logging.Logger):
    """Log server shutdown"""
    logger.info("🛑 SERVER SHUTTING DOWN")
    logger.info(f"Shutdown Time: {datetime.now().isoformat()}")


def log_request_metrics(logger: logging.Logger, server_stats: dict, tool_name: str, success: bool, duration: float):
    """Log request metrics"""
    server_stats["total_requests"] += 1

    # Ensure tool exists in the stats dictionary (for dynamically added tools)
    if tool_name not in server_stats["tools"]:
        server_stats["tools"][tool_name] = {"calls": 0, "errors": 0}

    server_stats["tools"][tool_name]["calls"] += 1

    if success:
        server_stats["successful_requests"] += 1
        logger.info(f"📊 TOOL_SUCCESS | {tool_name} | Duration: {duration:.3f}s")
    else:
        server_stats["failed_requests"] += 1
        server_stats["tools"][tool_name]["errors"] += 1
        logger.error(f"📊 TOOL_ERROR | {tool_name} | Duration: {duration:.3f}s")


def log_server_health(logger: logging.Logger, server_stats: dict):
    """Log periodic server health status"""
    uptime = time.time() - server_stats["start_time"]
    success_rate = (server_stats["successful_requests"] / max(server_stats["total_requests"], 1)) * 100

    logger.info("🏥 HEALTH_CHECK")
    logger.info(f"   Uptime: {uptime:.1f}s")
    logger.info(f"   Total Requests: {server_stats['total_requests']}")
    logger.info(f"   Success Rate: {success_rate:.1f}%")
    logger.info(f"   Active Tools: {len([t for t in server_stats['tools'] if server_stats['tools'][t]['calls'] > 0])}")


def create_server_stats():
    """Create and return initial server stats dictionary"""
    return {
        "start_time": time.time(),
        "total_requests": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "mcp_calls": {
            "tools/list": 0,
            "tools/call": 0,
            "initialize": 0
        },
        "tools": {
            "git_diff": {"calls": 0, "errors": 0},
            "git_classify_changes": {"calls": 0, "errors": 0},
            "git_mirror_sfdx_to_metadata": {"calls": 0, "errors": 0},
            "git_stage_and_commit": {"calls": 0, "errors": 0},
            "git_push": {"calls": 0, "errors": 0},
            "gh_create_pr": {"calls": 0, "errors": 0},
            "sf_list_orgs": {"calls": 0, "errors": 0},
            "sf_deploy_validate": {"calls": 0, "errors": 0},
        }
    }
