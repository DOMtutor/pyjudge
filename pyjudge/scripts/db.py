import pathlib
import yaml
from typing import Optional, Union

import mysql.connector
from mysql.connector.abstracts import MySQLConnectionAbstract
from mysql.connector.cursor import MySQLCursor


class DatabaseCursor(object):
    def __init__(self, connection: MySQLConnectionAbstract, **kwargs):
        self.connection = connection
        self.cursor = None
        self.args = kwargs

    def __enter__(self) -> MySQLCursor:
        self.cursor = self.connection.cursor(**self.args)
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cursor is not None:
            self.cursor.close()
        self.cursor = None
        return False


class DatabaseTransaction(object):
    def __init__(self, connection: MySQLConnectionAbstract, **kwargs):
        self.connection = connection
        self.args = kwargs
        self.transaction: Optional[MySQLConnectionAbstract] = None

    def cursor(self, **kwargs):
        assert self.transaction is not None
        return DatabaseCursor(self.transaction, **kwargs)

    def __enter__(self) -> MySQLConnectionAbstract:
        self.transaction = self.connection.start_transaction(**self.args)
        return self.transaction

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.transaction.rollback()
        else:
            self.transaction.commit()


class DatabaseTransactionCursor(object):
    def __init__(self, connection: MySQLConnectionAbstract,
                 readonly: bool = False,
                 isolation_level: Optional[str] = None,
                 buffered_cursor: bool = False,
                 prepared_cursor: bool = True):
        self.connection = connection
        self.readonly: bool = readonly
        self.isolation_level: Optional[str] = isolation_level
        self.buffered_cursor = buffered_cursor
        self.prepared_cursor = prepared_cursor

        self.cursor: Optional[MySQLCursor] = None

    def __enter__(self) -> MySQLCursor:
        self.connection.start_transaction(consistent_snapshot=True,
                                          isolation_level=self.isolation_level)
        self.cursor = self.connection.cursor(buffered=self.buffered_cursor,
                                             raw=False,
                                             prepared=self.prepared_cursor)
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cursor.close()
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()


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
        self._connection = mysql.connector.connect(host=self.host, port=self.port,
                                                   user=self.user, passwd=self.password,
                                                   database=self.database,
                                                   use_pure=False)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._connection.close()
        return False

    def transaction(self, **kwargs) -> DatabaseTransaction:
        return DatabaseTransaction(self._connection, **kwargs)

    def transaction_cursor(self,
                           readonly: bool = False,
                           isolation_level: Optional[str] = None,
                           buffered_cursor: bool = False,
                           prepared_cursor: bool = True) -> DatabaseTransactionCursor:
        return DatabaseTransactionCursor(self._connection, readonly, isolation_level, buffered_cursor, prepared_cursor)


def list_param(data):
    return f"({','.join(['?'] * len(data))})"


def get_unique(cursor: MySQLCursor):
    result = cursor.fetchall()
    if not result:
        raise ValueError("No result found")
    if len(result) > 1:
        raise ValueError("Multiple results found")
    return result[0]
