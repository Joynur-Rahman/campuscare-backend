from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.api.routes.router import router
from app.core.logger import CorrelationIdMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.api.routes.router import limiter


from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

app = FastAPI(title="CampusCare API", version="1.0.0", description="Complaint management backend for CampusCare")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(CorrelationIdMiddleware)

class SecurityHeadersMiddleware:
    async def __call__(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; img-src 'self' data: fastapi.tiangolo.com;"
        return response

app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"] if settings.app_env == "development" else ["campuscare.com", "*.campuscare.com"])
app.middleware("http")(SecurityHeadersMiddleware().__call__)

# Add CORSMiddleware last so it wraps all responses (including errors and security headers)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(set(settings.allowed_origins + ["http://localhost:5173", "http://127.0.0.1:5173"])),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code in (401, 403):
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"type=authorization_denial status={exc.status_code} msg={str(exc.detail)}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "HTTPException", "message": str(exc.detail), "details": []},
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"Validation Error: {exc.errors()} - Body: {exc.body}")
    details = [{"loc": ".".join(map(str, err.get("loc", []))), "msg": err.get("msg", ""), "type": err.get("type", "")} for err in exc.errors()]
    return JSONResponse(
        status_code=422,
        content={"error": "ValidationError", "message": "Invalid request payload", "details": details},
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"type=database_error Monitoring: Supabase/Internal error: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"error": "InternalServerError", "message": "An unexpected error occurred", "details": []},
    )
