"""Errors that end a command are reported in a few readable lines."""

import json
import logging
import pathlib

import pymysql
import pytest
import yaml

from pydomjudge.exc import (
    ConfigurationError,
    InvalidFileFormatError,
    describe_error,
    error_handler_wrapper,
)
from pydomjudge.model import Contest, JudgeInstance
from pydomjudge.scripts import _cli


def _broken_instance(
    examples_dir: pathlib.Path, tmp_path: pathlib.Path
) -> pathlib.Path:
    data = json.loads((examples_dir / "instance.json").read_text())
    data["base_time"] = "fast"
    data["team_categories"][0]["order"] = "first"
    path = tmp_path / "instance.json"
    path.write_text(json.dumps(data))
    return path


def test_validation_errors_name_file_and_location(examples_dir, tmp_path):
    path = _broken_instance(examples_dir, tmp_path)
    with pytest.raises(InvalidFileFormatError) as error:
        _cli.load_model(path, JudgeInstance)
    lines = str(error.value).splitlines()
    assert lines[0].startswith(f"{path}: base_time: Input should be a valid number")
    assert lines[1].startswith(f"{path}: team_categories[0].order: ")


def test_invalid_json_names_position(tmp_path):
    path = tmp_path / "contest.json"
    path.write_text('{"key": ')
    with pytest.raises(
        InvalidFileFormatError, match=r"contest.json: Invalid JSON: .*line"
    ):
        _cli.load_model(path, Contest)


def test_missing_file(tmp_path):
    with pytest.raises(ConfigurationError, match="contest.json: No such file"):
        _cli.load_model(tmp_path / "contest.json", Contest)


def test_database_file_problems(tmp_path):
    path = tmp_path / "db.yml"
    path.write_text("host: [unclosed\n")
    parser = _cli.make_parser(database=True)
    with pytest.raises(InvalidFileFormatError, match="db.yml: invalid YAML"):
        _cli.load_database(parser.parse_args(["--db", str(path)]))
    path.write_text("host: localhost\n")
    with pytest.raises(InvalidFileFormatError, match="db.yml: missing entry user"):
        _cli.load_database(parser.parse_args(["--db", str(path)]))


def test_describe_known_errors():
    assert describe_error(yaml.YAMLError("bad")).startswith("Invalid YAML")
    database = describe_error(pymysql.err.OperationalError(1045, "Access denied"))
    assert database.startswith("Database error: Access denied")
    assert describe_error(KeyError("x")) == "Unexpected error: KeyError('x')"


def test_wrapper_prints_message_and_exits(capsys, caplog):
    @error_handler_wrapper
    def failing():
        raise ConfigurationError("something is missing")

    @error_handler_wrapper
    def crashing():
        raise RuntimeError("boom")

    with pytest.raises(SystemExit) as exit_info:
        failing()
    assert exit_info.value.code == 1
    assert capsys.readouterr().err == "something is missing\n"

    with (
        caplog.at_level(logging.WARNING, logger="pydomjudge"),
        pytest.raises(SystemExit),
    ):
        crashing()
    err = capsys.readouterr().err
    assert "Unexpected error: RuntimeError('boom')" in err
    assert "--debug" in err and "Traceback" not in err
