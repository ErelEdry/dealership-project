"""
FastAPI application entry point.
Run: uvicorn main:app --reload
Docs: http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import bookings, search, vehicles
from app.core.config import settings

app = FastAPI(
    title="AI Car Dealership API",
    description="Intelligent inventory enrichment, semantic search, and booking platform.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS (origins from settings.cors_origins; default = Next.js on :3000) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Health check ─────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "environment": settings.environment}

# ── Routers (add more as phases progress) ────────────────────
app.include_router(search.router,   prefix="/api/search",   tags=["Search"])
app.include_router(vehicles.router, prefix="/api/vehicles", tags=["Vehicles"])
app.include_router(bookings.router, prefix="/api/bookings", tags=["Bookings"])
