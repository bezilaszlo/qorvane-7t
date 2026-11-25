import json
import logging
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import (
    DataError,
    DBAPIError,
    InterfaceError,
    OperationalError,
    SQLAlchemyError,
)
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.db import DatabaseUnavailableError

logger = logging.getLogger(__name__)

MAX_ECHO_CHARS = 200
UNAVAILABLE = {"detail": "database unavailable"}
QUERY_CANCELED = "57014"
LOCK_NOT_AVAILABLE = "55P03"
BUSY_DETAILS = {QUERY_CANCELED: "query timed out", LOCK_NOT_AVAILABLE: "database busy"}


def validation_error(loc: tuple[str, ...], msg: str, type_: str) -> RequestValidationError:
    return RequestValidationError([{"type": type_, "loc": loc, "msg": msg}])


def _echoable(value: Any) -> bool:
    try:
        return len(json.dumps(value, allow_nan=False)) <= MAX_ECHO_CHARS
    except (TypeError, ValueError):
        return False


async def request_validation_handler(request: Request, exc: Exception) -> JSONResponse:
    detail = []
    for err in cast(RequestValidationError, exc).errors():
        item = {"type": err["type"], "loc": list(err["loc"]), "msg": err["msg"]}
        if "input" in err and _echoable(err["input"]):
            item["input"] = err["input"]
        detail.append(item)
    return JSONResponse(status_code=422, content={"detail": detail})


def _is_connection_failure(exc: SQLAlchemyError) -> bool:
    if isinstance(exc, OperationalError | InterfaceError | PoolTimeoutError):
        return True
    return isinstance(exc, DBAPIError) and exc.connection_invalidated


def _sqlstate(exc: Exception) -> str:
    # asyncpg reports some data exceptions (e.g. float overflow) as a generic DBAPIError.
    orig = getattr(exc, "orig", None)
    code = getattr(orig, "sqlstate", None) or getattr(
        getattr(orig, "__cause__", None), "sqlstate", None
    )
    return code or ""


async def database_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if busy := BUSY_DETAILS.get(_sqlstate(exc)):
        logger.warning("database timeout (%s): %r", busy, exc)
        return JSONResponse(status_code=503, content={"detail": busy})
    if isinstance(exc, SQLAlchemyError) and _is_connection_failure(exc):
        logger.warning("database unavailable: %r", exc)
        return JSONResponse(status_code=503, content=UNAVAILABLE)
    if isinstance(exc, DataError) or _sqlstate(exc).startswith("22"):
        detail = [{"type": "value_error", "loc": ["query"], "msg": "numeric value out of range"}]
        return JSONResponse(status_code=422, content={"detail": detail})
    logger.error("unhandled database error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


async def unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("database unavailable: %r", exc.__cause__ or exc)
    return JSONResponse(status_code=503, content=UNAVAILABLE)


def register_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(SQLAlchemyError, database_error_handler)
    app.add_exception_handler(DatabaseUnavailableError, unavailable_handler)
