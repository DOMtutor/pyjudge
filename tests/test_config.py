"""pyjudge.yaml, the user configuration and the command line."""

import argparse
import pathlib

import pytest

from pydomjudge.exc import InvalidFileFormatError
from pydomjudge.scripts import _cli, _config, commands


@pytest.fixture
def project(tmp_path, monkeypatch) -> pathlib.Path:
    """A project with pyjudge.yaml and a subdirectory as working directory."""
    (tmp_path / "pyjudge.yaml").write_text(
        "database: secrets/db.yml\nrepository: problems-repo\ninstance: judge.json\n"
        "users: users.json\n"
    )
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    return tmp_path


def test_project_file_found_from_subdirectory(project):
    value, source = _config.lookup("instance", None)
    assert value == project / "judge.json"  # relative to the file
    assert source == str(project / "pyjudge.yaml")


def test_command_line_wins(project):
    assert _config.lookup("instance", pathlib.Path("x.json")) == (
        pathlib.Path("x.json"),
        "command line",
    )
    args = commands.build_parser().parse_args(
        ["upload", "users", "--instance", "x.json"]
    )
    assert _cli.setting(args, "instance") == pathlib.Path("x.json")
    assert _cli.setting(args, "users") == project / "users.json"


def test_user_file_is_the_lower_layer(project, tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("home")
    (home / "pyjudge").mkdir()
    (home / "pyjudge" / "config.yaml").write_text(
        "contest: c.json\ninstance: other.json\n"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    assert _config.lookup("contest", None)[0] == home / "pyjudge" / "c.json"
    assert _config.lookup("instance", None)[0] == project / "judge.json"


def test_nothing_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _config.lookup("repository", None) == (None, "default")


def test_inline_database_with_password_from_environment(tmp_path, monkeypatch):
    (tmp_path / "pyjudge.yaml").write_text(
        "database: {host: db.example, user: domjudge, password_env: DB_PASSWORD}\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DB_PASSWORD", "secret")
    database = _cli.load_database(argparse.Namespace(db=None))
    assert (database.host, database.port, database.password) == (
        "db.example",
        3306,
        "secret",
    )
    monkeypatch.delenv("DB_PASSWORD")
    with pytest.raises(InvalidFileFormatError, match="DB_PASSWORD is not set"):
        _cli.load_database(argparse.Namespace(db=None))


def test_invalid_project_file(tmp_path, monkeypatch):
    (tmp_path / "pyjudge.yaml").write_text("repositry: x\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(
        InvalidFileFormatError, match="pyjudge.yaml: repositry: Extra inputs"
    ):
        _config.lookup("repository", None)


def test_init_and_config(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    commands.main(["init"])
    assert {path.name for path in tmp_path.iterdir()} == {
        "pyjudge.yaml",
        "db.yml",
        "instance.json",
    }
    database = _cli.load_database(argparse.Namespace(db=None))
    assert (database.user, database.database) == ("domjudge", "domjudge")
    instance = _cli.load_instance(argparse.Namespace(instance=None))
    assert instance.team_categories

    (tmp_path / "db.yml").write_text("changed")
    commands.main(["init"])
    assert (tmp_path / "db.yml").read_text() == "changed"  # not overwritten

    capsys.readouterr()
    commands.main(["config", "--instance", "x.json"])
    out = capsys.readouterr().out
    assert str(tmp_path / "pyjudge.yaml") in out
    assert "x.json  [command line]" in out
    assert "contest     (default: none)" in out
