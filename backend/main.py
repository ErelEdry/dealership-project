"""
FastAPI application entry point.
Run: uvicorn main:app --reload
Docs: http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings

app = FastAPI(
    title="AI Car Dealership API",
    description="Intelligent inventory enrichment, semantic search, and booking platform.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS (allow Next.js dev server) ──────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Health check ─────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "environment": settings.environment}

# ── Routers (add more as phases progress) ────────────────────
# from app.api.routes import inventory, search, bookings
# app.include_router(inventory.router, prefix="/api/inventory", tags=["Inventory"])
# app.include_router(search.router,    prefix="/api/search",    tags=["Search"])
# app.include_router(bookings.router,  prefix="/api/bookings",  tags=["Bookings"])
