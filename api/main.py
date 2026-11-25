"""ERPClaw Web API — FastAPI application."""

import logging
import os
import sys
from contextlib import closing
from pathlib import Path

# Ensure api/ directory is on the Python path
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from auth.middleware import AuthMiddleware
from auth.routes import router as auth_router
from skills.routes import router as skills_router
from layout import router as layout_router
from chat.routes import router as chat_router
from db import get_erp_pg_db
from erp_routes import router as erp_router
from ws import router as ws_router
from init_db import init_web_db

logger = logging.getLogger("uvicorn.error")

# Initialize database on startup
init_web_db()

# Production mode disables Swagger UI
_is_production = os.environ.get("ERPCLAW_ENV", "development") == "production"

app = FastAPI(
    title="ERPClaw Web API",
    version="1.0.0",
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)

# CORS — configurable origins via environment variable
_default_origins = "http://localhost:5173,http://localhost:5180,http://localhost:4173"
_origins = os.environ.get("ALLOWED_ORIGINS", _default_origins).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Auth middleware (after CORS so preflight passes)
app.add_middleware(AuthMiddleware)

# Mount routers
app.include_router(auth_router)
app.include_router(layout_router)
app.include_router(skills_router)
app.include_router(chat_router)
app.include_router(erp_router)
app.include_router(ws_router)


@app.get("/api/health")
def health():
    """Health check endpoint."""
    if _is_production or os.environ.get("ERPCLAW_DB_URL"):
        try:
            with closing(get_erp_pg_db()) as conn, conn.cursor() as cursor:
                cursor.execute("SELECT 1 FROM company LIMIT 1")
        except Exception as exc:
            logger.warning("ERP readiness check failed (%s)", type(exc).__name__)
            raise HTTPException(status_code=503, detail="ERP database unavailable") from exc
        return {"status": "ok", "version": "1.0.0", "erp_database": "ok"}
    return {"status": "ok", "version": "1.0.0"}


# Railway runs the API and frontend in one service. Serve the SvelteKit
# adapter-static output after the API routes so /api/* and /ws keep their
# existing handlers while browser-side routes fall back to index.html.
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "build"
_FRONTEND_ROOT = _FRONTEND_DIR.resolve()


@app.get("/{path:path}")
async def frontend(path: str):
    """Serve built frontend assets and support SvelteKit client-side routes."""
    if os.environ.get("ERPCLAW_API_ONLY") == "1" or not _FRONTEND_DIR.is_dir():
        raise HTTPException(status_code=404, detail="Frontend build not found")

    candidate = (_FRONTEND_DIR / path).resolve()
    if candidate != _FRONTEND_ROOT and _FRONTEND_ROOT not in candidate.parents:
        raise HTTPException(status_code=404, detail="Not found")

    if candidate.is_file():
        return FileResponse(candidate)

    index_file = _FRONTEND_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="Frontend entrypoint not found")
