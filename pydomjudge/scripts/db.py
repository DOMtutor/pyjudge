import argparse
import pathlib
from typing import Optional, Union, Protocol, Any, Iterator, Sequence

import pymysql
import yaml
from pymysql.connections import Connection
from pymysql.cursors import Cursor


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


class DatabaseTransactionCursor(object):
    def __init__(
        self,
        connection: Connection,
    ):
        self.connection = connection
        self.cursor: Optional[Cursor] = None

    def __enter__(self) -> DBCursor:
        self.cursor = self.connection.cursor()
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.cursor.close()


class Database(object):
    def __init__(self, config: Union[pathlib.Path, dict]):
        if isinstance(config, pathlib.Path):
            with config.open(mode="rt") as f:
                config = yaml.safe_load(f)

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
        self._connection.close()

    def transaction_cursor(
        self,
        readonly: bool = False,  # TODO Implement
    ) -> DatabaseTransactionCursor:
        return DatabaseTransactionCursor(
            self._connection,
        )


def list_param(data):
    return f"({','.join(['%s'] * len(data))})"


def field_in_list(field, allowed):
    if allowed:
        return f"{field} IN {list_param(allowed)}"
    return "1 = 2"


def field_not_in_list(field, allowed):
    if allowed:
        return f"{field} NOT IN {list_param(allowed)}"
    return "1 = 1"


def get_unique(cursor: DBCursor):
    result = cursor.fetchall()
    if not result:
        raise ValueError("No result found")
    if len(result) > 1:
        raise ValueError("Multiple results found")
    return result[0]


def make_argparse(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--db", type=pathlib.Path, default="db.yml", help="Path to database config"
    )


def from_args(args: argparse.Namespace) -> Database:
    return Database(args.db)
