"""Postgres access: one connection pool per process, dict rows everywhere."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from bioverse.config import get_settings

_pool: ConnectionPool | None = None


def open_pool(database_url: str | None = None) -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=database_url or get_settings().database_url,
            kwargs={"row_factory": dict_row},
            min_size=1,
            max_size=10,
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def get_conn() -> Iterator[Connection]:
    """One transaction per request: commit on success, roll back on error."""
    pool = open_pool()
    with pool.connection() as conn:
        yield conn


# scope="function" commits BEFORE the response is sent. With the default ("request") scope the
# commit runs after the client already has its answer, so a fast follow-up request can miss the write.
DbConn = Annotated[Connection, Depends(get_conn, scope="function")]
