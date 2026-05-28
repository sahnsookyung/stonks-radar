from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from frw_api.auth.bootstrap import ensure_bootstrap_admin
from frw_api.core.logging import configure_logging
from frw_api.core.security_headers import security_headers_middleware
from frw_api.core.settings import get_settings
from frw_api.routers import admin, auth, internal, public
from frw_api.services.rate_limit import rate_limit_middleware

configure_logging()
settings = get_settings()

app = FastAPI(
    title="Stonks Radar API",
    version="0.1.0",
    docs_url="/api/docs" if settings.app_env != "production" else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.app_env != "production" else None,
)

app.middleware("http")(security_headers_middleware)
app.middleware("http")(rate_limit_middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "x-csrf-token", "x-stonks-timestamp", "x-stonks-nonce", "x-stonks-email-signature"],
)


@app.on_event("startup")
def startup() -> None:
    ensure_bootstrap_admin()


app.include_router(public.router, prefix="/api/public", tags=["public"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(internal.router, prefix="/api/internal", tags=["internal"])
