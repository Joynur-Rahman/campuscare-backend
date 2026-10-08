import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Context variable to hold the correlation ID for the current request
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")

class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""
    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "correlation_id": correlation_id_ctx.get(),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)

def setup_logger() -> logging.Logger:
    """Configures and returns the structured logger."""
    logger = logging.getLogger("campuscare")
    logger.setLevel(logging.INFO)
    
    # Prevent adding handlers multiple times
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        
    return logger

logger = setup_logger()

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware to assign and manage correlation IDs for requests."""
    async def dispatch(self, request: Request, call_next) -> Response:
        # Check if the client sent a correlation ID, otherwise generate one
        corr_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        
        # Set the context variable
        token = correlation_id_ctx.set(corr_id)
        
        try:
            logger.info(f"Request started: {request.method} {request.url.path}")
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = corr_id
            logger.info(f"Request completed: {request.method} {request.url.path} - Status: {response.status_code}")
            return response
        finally:
            correlation_id_ctx.reset(token)
