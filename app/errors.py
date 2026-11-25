import json
import logging
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError, SQLAlchemyError

logger = logging.getLogger(__name__)


def validation_error(loc: tuple[str, ...], msg: str, type_: str) -> RequestValidationError:
    return RequestValidationError([{"type": type_, "loc": loc, "msg": msg}])


def _json_safe(value: Any) -> bool:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True


async def request_validation_handler(request: Request, exc: Exception) -> JSONResponse:
    detail = []
    for err in cast(RequestValidationError, exc).errors():
        item = {"type": err["type"], "loc": list(err["loc"]), "msg": err["msg"]}
        if "input" in err and _json_safe(err["input"]):
            item["input"] = err["input"]
        detail.append(item)
    return JSONResponse(status_code=422, content={"detail": detail})


def _is_connection_failure(exc: SQLAlchemyError) -> bool:
    if isinstance(exc, OperationalError | InterfaceError):
        return True
    return isinstance(exc, DBAPIError) and exc.connection_invalidated


async def database_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, SQLAlchemyError) and _is_connection_failure(exc):
        logger.warning("database unavailable: %r", exc)
        return JSONResponse(status_code=503, content={"detail": "database unavailable"})
    logger.exception("unhandled database error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


async def connection_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("database unavailable: %r", exc)
    return JSONResponse(status_code=503, content={"detail": "database unavailable"})


def register_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(SQLAlchemyError, database_error_handler)
    # Network-level failures reaching the DB (refused, DNS, timeout) surface as OSError.
    app.add_exception_handler(OSError, connection_error_handler)
