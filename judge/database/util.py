import pathlib
from typing import Optional, Union

import mysql.connector
import yaml
from mysql.connector.abstracts import MySQLConnectionAbstract
from mysql.connector.cursor import MySQLCursor


def list_param(data):
    return f"({','.join(['?'] * len(data))})"


def get_unique(cursor: MySQLCursor):
    result = cursor.fetchall()
    if not result:
        raise ValueError("No result found")
    if len(result) > 1:
        raise ValueError("Multiple results found")
    return result[0]


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
    DEFAULT = {
        "user": "domjudge",
        "password": "domjudge",
        "database": "domjudge",
        "host": "localhost",
        "port": 3306
    }
    KEYS = set(DEFAULT.keys())

    @staticmethod
    def check_config(config):
        if not isinstance(config, dict):
            raise TypeError("Malformed DB config")
        for key, value in config.items():
            if key not in Database.KEYS:
                raise KeyError(f"Malformed DB config, key {key} unknown")
            if not isinstance(value, type(Database.DEFAULT[key])):
                raise TypeError(f"Malformed DB config, key {key} has unexpected type")

    def __init__(self, config: Union[pathlib.Path, dict] = None):
        base_config = dict(Database.DEFAULT)
        if isinstance(config, pathlib.Path):
            with config.open(mode="rt") as f:
                config = yaml.safe_load(f)
            Database.check_config(config)
        if isinstance(config, dict):
            base_config.update(config)
        self.config = base_config
        self.connection = None

    def transaction(self, **kwargs):
        return DatabaseTransaction(self.connection, **kwargs)

    def transaction_cursor(self,
                           readonly: bool = False,
                           isolation_level: Optional[str] = None,
                           buffered_cursor: bool = False,
                           prepared_cursor: bool = True) -> DatabaseTransactionCursor:
        return DatabaseTransactionCursor(self.connection, readonly, isolation_level, buffered_cursor, prepared_cursor)

    def __enter__(self):
        self.connection = mysql.connector.connect(
            host=self.config["host"],
            port=self.config["port"],
            user=self.config["user"],
            passwd=self.config["password"],
            database=self.config["database"]
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.connection.close()
        return False


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