import logging
from logging.handlers import RotatingFileHandler
import os
import sys
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
    # ✅ Use original stderr to avoid stdio transport hijack
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
    logger.info("🚀 SALESFORCE MCP SERVER STARTING")
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
    logger.info("✅ SERVER READY — accepting connections")

def log_server_shutdown(logger: logging.Logger):
    """Log server shutdown"""
    logger.info("🛑 SERVER SHUTTING DOWN")

def log_request_metrics(logger: logging.Logger, server_stats: dict, tool_name: str, success: bool, duration: float):
    """Log and record metrics for a tool invocation"""
    server_stats["total_requests"] += 1
    if success:
        server_stats["successful_requests"] += 1
    else:
        server_stats["failed_requests"] += 1
    status = "✅" if success else "❌"
    logger.info(f"{status} TOOL_END | {tool_name} | success={success} | duration={duration:.3f}s")

def log_server_health(logger: logging.Logger, server_stats: dict):
    """Periodically log server health/stats"""
    import time
    uptime = time.time() - server_stats["start_time"]
    logger.info(
        f"💓 HEALTH | uptime={uptime:.0f}s | total={server_stats['total_requests']} "
        f"| ok={server_stats['successful_requests']} | failed={server_stats['failed_requests']}"
    )

def setup_mcp_logging():
    pass

def create_server_stats() -> dict:
    import time
    return {
        "start_time": time.time(),
        "total_requests": 0,
        "successful_requests": 0,
        "failed_requests": 0,
    }
