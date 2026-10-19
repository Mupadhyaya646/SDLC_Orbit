"""
Middleware for filtering noisy logs and adding request tracking
"""
import logging
import time
from app.logger import get_logger

logger = get_logger(__name__)

class RequestLoggingFilter(logging.Filter):
    """Filter to reduce noise from health check and metrics endpoints"""

    def __init__(self):
        super().__init__()
        self.noisy_patterns = [
            "/metrics",
            "/health",
            "/healthz",
            "/favicon.ico",
            "/robots.txt"
        ]

    def filter(self, record):
        """Filter out noisy log records"""
        if hasattr(record, 'getMessage'):
            message = record.getMessage()

            # Filter out noisy endpoints
            for pattern in self.noisy_patterns:
                if pattern in message and "404 Not Found" in message:
                    return False

            # Filter uvicorn startup messages we don't need
            if any(phrase in message for phrase in [
                "Started server process",
                "Waiting for application startup",
                "Application startup complete"
            ]):
                return False

        return True

def setup_uvicorn_logging():
    """Setup custom logging for uvicorn to reduce noise"""

    # Get uvicorn access logger and add our filter
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.addFilter(RequestLoggingFilter())

    # Reduce uvicorn log level to WARNING to hide routine messages
    uvicorn_access.setLevel(logging.WARNING)

    # Also filter the main uvicorn logger
    uvicorn_main = logging.getLogger("uvicorn")
    uvicorn_main.setLevel(logging.WARNING)

    logger.info("🔇 Configured uvicorn logging filters to reduce noise")

def log_request_summary(method: str, path: str, status_code: int, duration: float):
    """Log important requests only"""

    # Skip logging for noisy endpoints
    noisy_paths = ["/metrics", "/health", "/healthz", "/favicon.ico", "/robots.txt"]
    if any(noisy_path in path for noisy_path in noisy_paths):
        return

    # Log important requests
    if status_code >= 400:
        logger.warning(f"🚨 HTTP_ERROR | {method} {path} | Status: {status_code} | Duration: {duration:.3f}s")
    elif path.startswith("/api/") or "tool" in path.lower():
        logger.info(f"🌐 HTTP_REQUEST | {method} {path} | Status: {status_code} | Duration: {duration:.3f}s")
