"""The connection settings of a db.yml file."""

import os
import pathlib
from typing import Any

import pydantic
import yaml

from pydomjudge.exc import (
    ConfigurationError,
    InvalidFileFormatError,
    validation_problems,
)


class DatabaseConfig(pydantic.BaseModel, extra="forbid"):
    """Connection to DOMjudge's database, as in db.yml."""

    host: str
    port: int = 3306
    user: str
    password: str | None = None
    # Name of an environment variable holding the password, to keep it out of
    # files under version control
    password_env: str | None = None
    database: str = "domjudge"

    @pydantic.model_validator(mode="after")
    def _one_password(self):
        if (self.password is None) == (self.password_env is None):
            raise ValueError("set exactly one of password and password_env")
        return self

    def connection(self, source: pathlib.Path | None) -> dict[str, Any]:
        """The arguments of Database(); reads password_env now."""
        password = self.password
        if self.password_env is not None:
            password = os.environ.get(self.password_env)
            if password is None:
                raise InvalidFileFormatError(
                    source, f"environment variable {self.password_env} is not set"
                )
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": password,
            "database": self.database,
        }


def read_database_file(path: pathlib.Path) -> DatabaseConfig:
    """The settings of a db.yml file (host, port, user, password or
    password_env, database)."""
    if not path.is_file():
        raise ConfigurationError(f"No database configuration found at {path}")
    try:
        with path.open(mode="rt") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise InvalidFileFormatError(path, f"invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise InvalidFileFormatError(path, "expected a mapping (host, user, ...)")
    try:
        return DatabaseConfig.model_validate(data)
    except pydantic.ValidationError as e:
        raise InvalidFileFormatError(
            path, *validation_problems(e), what="database configuration"
        ) from e
