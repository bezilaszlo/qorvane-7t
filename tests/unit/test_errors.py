from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, model_validator
from sqlalchemy.exc import DataError, DBAPIError, IntegrityError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.db import ConnDep, ReadConnDep
from app.errors import register_handlers


class Body(BaseModel):
    value: float
    items: list[int] = []

    @model_validator(mode="after")
    def _always_fail(self):
        raise ValueError("model-level failure")


class FakeEngine:
    def __init__(self, enter: Exception | None = None, exit_: Exception | None = None):
        self.enter, self.exit_ = enter, exit_

    @asynccontextmanager
    async def begin(self) -> AsyncGenerator[object]:
        if self.enter:
            raise self.enter
        yield object()
        if self.exit_:
            raise self.exit_


def make_client(
    engine: FakeEngine, raised: Exception | None = None, *, strict: bool = True
) -> TestClient:
    app = FastAPI()
    register_handlers(app)
    app.state.engine = engine

    @app.post("/write", status_code=201)
    async def write(conn: ConnDep) -> dict[str, str]:
        if raised:
            raise raised
        return {"status": "created"}

    @app.get("/read")
    async def read() -> dict[str, str]:
        if raised:
            raise raised
        return {"status": "ok"}

    @app.post("/body")
    async def body(payload: Body) -> None: ...

    return TestClient(app, raise_server_exceptions=strict)


def db_error(cls: type[Exception]) -> Exception:
    return cls("stmt", {}, Exception("boom"))


def test_commit_failure_is_not_acknowledged():
    client = make_client(FakeEngine(exit_=db_error(OperationalError)))
    response = client.post("/write")
    assert response.status_code == 503


def test_successful_commit_is_acknowledged():
    assert make_client(FakeEngine()).post("/write").status_code == 201


def test_connect_level_os_error_is_503():
    response = make_client(FakeEngine(enter=ConnectionRefusedError())).post("/write")
    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}


@pytest.mark.parametrize(
    "exc",
    [db_error(OperationalError), db_error(InterfaceError), PoolTimeoutError("pool")],
    ids=["operational", "interface", "pool-timeout"],
)
def test_connection_level_db_errors_are_503(exc):
    assert make_client(FakeEngine(), raised=exc).post("/write").status_code == 503


def test_other_db_errors_are_generic_500():
    client = make_client(FakeEngine(), raised=db_error(IntegrityError), strict=False)
    response = client.post("/write")
    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}


@pytest.mark.parametrize(
    ("method", "path", "expected_loc"),
    [("POST", "/write", ["body"]), ("GET", "/read", ["query"])],
    ids=["post-body", "get-query"],
)
def test_data_error_is_422(method, path, expected_loc):
    response = make_client(FakeEngine(), raised=db_error(DataError)).request(method, path)
    assert response.status_code == 422
    err = response.json()["detail"][0]
    assert err["msg"] == "numeric value out of range"
    assert err["loc"] == expected_loc


def test_non_db_os_error_is_not_labelled_unavailable():
    client = make_client(FakeEngine(), raised=PermissionError("nope"), strict=False)
    assert client.post("/write").status_code == 500


def test_validation_error_keeps_small_input_and_drops_huge_input():
    client = make_client(FakeEngine())
    small = client.post("/body", json={"value": "x"}).json()["detail"][0]
    assert small["input"] == "x"
    huge = client.post("/body", json={"value": 1, "items": list(range(5000))}).json()
    assert all("input" not in err for err in huge["detail"])


class FakeAsyncpgError(Exception):
    sqlstate = "22003"


def test_generic_dbapi_error_with_data_exception_sqlstate_is_422():
    exc = DBAPIError("stmt", {}, FakeAsyncpgError("overflow"))
    assert make_client(FakeEngine(), raised=exc).post("/write").status_code == 422


class FakeCanceled(Exception):
    sqlstate = "57014"


class FakeLockTimeout(Exception):
    sqlstate = "55P03"


@pytest.mark.parametrize(
    ("sqlstate_cls", "detail"),
    [(FakeCanceled, "query timed out"), (FakeLockTimeout, "database busy")],
    ids=["statement-timeout", "lock-timeout"],
)
@pytest.mark.parametrize("wrapper", [DBAPIError, OperationalError], ids=["dbapi", "operational"])
def test_timeouts_are_503_with_generic_detail(sqlstate_cls, detail, wrapper):
    exc = wrapper("SELECT secret", {}, sqlstate_cls("canceling statement"))
    response = make_client(FakeEngine(), raised=exc).post("/write")
    assert response.status_code == 503
    assert response.json() == {"detail": detail}


class FakeReadConn:
    def __init__(self):
        self.options: dict = {}

    async def execution_options(self, **options):
        self.options = options
        return self


class FakeReadEngine:
    def __init__(self, enter: Exception | None = None):
        self.enter, self.conn, self.began = enter, FakeReadConn(), False

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[FakeReadConn]:
        if self.enter:
            raise self.enter
        yield self.conn

    def begin(self):
        self.began = True
        raise AssertionError("reads must not open a transaction")


def make_read_client(engine: FakeReadEngine) -> TestClient:
    app = FastAPI()
    register_handlers(app)
    app.state.engine = engine

    @app.get("/read")
    async def read(conn: ReadConnDep) -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


def test_read_dependency_uses_autocommit_without_transaction():
    engine = FakeReadEngine()
    assert make_read_client(engine).get("/read").status_code == 200
    assert engine.conn.options == {"isolation_level": "AUTOCOMMIT"}
    assert not engine.began


def test_read_dependency_connect_failure_is_503():
    response = make_read_client(FakeReadEngine(enter=ConnectionRefusedError())).get("/read")
    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}
