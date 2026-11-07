"""FastAPI application entry point.

Configures application lifespan, database initialization, background scheduler,
exception handlers, and registers all API routers and dashboard UI.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, conflicts, letterboxd, status, sync
from app.core.exceptions import SyncError
from app.db.database import init_db
from app.services.scheduler import shutdown_scheduler, start_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database schema and start background scheduler
    await init_db()
    start_scheduler()
    yield
    # Shutdown: Stop scheduler
    shutdown_scheduler()


app = FastAPI(
    title="Trakt ↔ Letterboxd Sync Service",
    description="Trakt-authoritative automated synchronization with a Letterboxd CSV bridge",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(auth.router)
app.include_router(letterboxd.router)
app.include_router(sync.router)
app.include_router(conflicts.router)
app.include_router(status.router)


@app.exception_handler(SyncError)
async def sync_error_handler(request: Request, exc: SyncError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "error_type": exc.__class__.__name__, **exc.details},
    )


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the single-page sync dashboard."""
    html_path = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Trakt ↔ Letterboxd Sync Service Running</h1>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
