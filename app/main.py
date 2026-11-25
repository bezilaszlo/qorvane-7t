from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.api import health, readings, sensors, stats
from app.config import get_settings
from app.db import create_engine

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    engine = create_engine(get_settings())
    app.state.engine = engine
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="Weather sensor metrics", version="0.1.0", lifespan=lifespan)


@app.exception_handler(SQLAlchemyError)
@app.exception_handler(OSError)
@app.exception_handler(TimeoutError)
async def database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "database unavailable"})


app.include_router(health.router)
app.include_router(readings.router)
app.include_router(stats.router)
app.include_router(sensors.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
