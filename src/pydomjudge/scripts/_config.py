"""Configuration files of the command line.

Settings are looked up in this order, the first that has a value wins:
command line option, the project file ``pyjudge.yaml`` (the first one found
in the working directory or one of its parents), the user file
``~/.config/pyjudge/config.yaml`` (or in ``$XDG_CONFIG_HOME``), built-in
default. Paths in a file are relative to that file.
"""

import dataclasses
import os
import pathlib
from typing import Any

import pydantic
import yaml

from pydomjudge.exc import InvalidFileFormatError, validation_problems

PROJECT_FILE = "pyjudge.yaml"


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


class ConfigFile(pydantic.BaseModel, extra="forbid"):
    """pyjudge.yaml or the user configuration."""

    # A db.yml-like file, or the connection itself
    database: pathlib.Path | DatabaseConfig | None = None
    repository: pathlib.Path | None = None
    instance: pathlib.Path | None = None
    users: pathlib.Path | None = None
    contest: pathlib.Path | None = None


SETTINGS = [field for field in ConfigFile.model_fields]


@dataclasses.dataclass(frozen=True)
class Layer:
    path: pathlib.Path
    config: ConfigFile

    def get(self, name: str) -> Any:
        value = getattr(self.config, name)
        if isinstance(value, pathlib.Path):
            return (self.path.parent / value).resolve()
        return value


def read_file(path: pathlib.Path) -> Layer:
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise InvalidFileFormatError(path, f"invalid YAML: {e}") from e
    try:
        return Layer(path, ConfigFile.model_validate(data))
    except pydantic.ValidationError as e:
        raise InvalidFileFormatError(path, *validation_problems(e)) from e


def find_project_file(start: pathlib.Path) -> pathlib.Path | None:
    for directory in [start, *start.parents]:
        candidate = directory / PROJECT_FILE
        if candidate.is_file():
            return candidate
    return None


def user_file() -> pathlib.Path:
    base = os.environ.get("XDG_CONFIG_HOME") or pathlib.Path.home() / ".config"
    return pathlib.Path(base) / "pyjudge" / "config.yaml"


def layers(start: pathlib.Path | None = None) -> list[Layer]:
    """The configuration files that apply, most important first."""
    result = []
    project = find_project_file((start or pathlib.Path.cwd()).resolve())
    if project is not None:
        result.append(read_file(project))
    home = user_file()
    if home.is_file() and (project is None or home.resolve() != project.resolve()):
        result.append(read_file(home))
    return result


def lookup(
    name: str, option: Any, start: pathlib.Path | None = None
) -> tuple[Any, str]:
    """The value of a setting and where it comes from."""
    if option is not None:
        return option, "command line"
    for layer in layers(start):
        value = layer.get(name)
        if value is not None:
            return value, str(layer.path)
    return None, "default"


PROJECT_TEMPLATE = """\
# pydomjudge project configuration, found by pyjudge in this directory and below.
# Paths are relative to this file; command line options override the values.

# Connection to DOMjudge's database: a file like db.yml (keep it out of version
# control), or the connection itself, e.g.
#   database: {host: 127.0.0.1, user: domjudge, password_env: DOMJUDGE_DB_PASSWORD}
database: db.yml
repository: repository
instance: instance.json
users: users.json
# contest: contest.json
"""

DATABASE_TEMPLATE = """\
# DOMjudge database connection (password: DOMJUDGE_DB_DOMJUDGE_PASSWORD of the
# docker-compose .env); keep this file out of version control
host: 127.0.0.1
port: 3306
user: domjudge
password: domjudge
database: domjudge
"""
