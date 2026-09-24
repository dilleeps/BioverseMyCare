"""Bioverse API.

Run locally:
    uvicorn bioverse.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import importlib
import pkgutil

from bioverse import routers
from bioverse.config import get_settings
from bioverse.db import close_pool, open_pool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    open_pool()
    yield
    close_pool()


app = FastAPI(
    title="Bioverse One API",
    version="0.1.0",
    description="AI-powered healthcare companion and orchestration platform.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Every module in bioverse/routers that defines `router` is mounted. Adding a module never
# requires editing this file.
for info in sorted(pkgutil.iter_modules(routers.__path__), key=lambda m: m.name):
    module = importlib.import_module(f"{routers.__name__}.{info.name}")
    if hasattr(module, "router"):
        app.include_router(module.router)

# Serve the built React app when it exists (single-process deployment).
WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not found")
        candidate = (WEB_DIST / path).resolve()
        if path and candidate.is_file() and WEB_DIST in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
