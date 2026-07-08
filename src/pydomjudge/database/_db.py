from typing import Optional, Protocol, Any, Iterator, Sequence

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import Cursor

from pydomjudge.exc import ElementNotFoundError, MultipleElementsFoundError


class DBCursor(Protocol):
    def execute(self, query: str, params: Any = ...) -> Any: ...

    def fetchone(self) -> Optional[tuple[Any, ...]]: ...

    def fetchmany(self, size: int = ...) -> list[tuple[Any, ...]]: ...

    def fetchall(self) -> list[tuple[Any, ...]]: ...

    def close(self) -> None: ...

    def __iter__(self) -> Iterator[tuple[Any, ...]]: ...

    rowcount: int
    lastrowid: Optional[int]
    arraysize: int
    description: Optional[Sequence[tuple]]


# noinspection PyTypeChecker
class DatabaseTransactionCursor(object):
    def __init__(
        self,
        connection: Connection,
    ):
        self.connection = connection
        self.cursor: Cursor | None = None

    def __enter__(self) -> DBCursor:
        self.cursor = self.connection.cursor()
        assert self.cursor is not None
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        if self.cursor is not None:
            self.cursor.close()


class Database(object):
    def __init__(self, **config):
        self.host = config["host"]
        self.port = config.get("port", 3306)
        self.user = config["user"]
        self.password = config["password"]
        self.database = config["database"]
        self._connection = None

    def __enter__(self):
        self._connection = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            passwd=self.password,
            database=self.database,
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._connection is not None:
            self._connection.close()

    def transaction_cursor(
        self,
        readonly: bool = False,  # TODO Implement
    ) -> DatabaseTransactionCursor:
        assert self._connection is not None
        return DatabaseTransactionCursor(
            self._connection,
        )


def list_param(data):
    return f"({','.join(['%s'] * len(data))})"


def field_in_list(field, allowed):
    if allowed:
        return f"{field} IN {list_param(allowed)}"
    return "1 = 2"


def field_not_in_list(field, prohibited):
    if prohibited:
        return f"{field} NOT IN {list_param(prohibited)}"
    return "1 = 1"


def get_unique(cursor: DBCursor):
    result = cursor.fetchmany(2)
    if not result:
        raise ElementNotFoundError("No result found")
    if len(result) > 1:
        raise MultipleElementsFoundError("Multiple results found")
    return result[0]


def get_unique_with_error(
    cursor: DBCursor, query_name: Any, name: str, plural_name: str | None = None
):
    result = cursor.fetchmany(2)
    if not result:
        raise ElementNotFoundError(f"No {name} found for {query_name}")
    if len(result) > 1:
        raise MultipleElementsFoundError(
            f"Multiple {plural_name if plural_name else name} found for {query_name}"
        )
    return result[0]
