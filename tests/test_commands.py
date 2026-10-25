"""The pyjudge command tree."""

import argparse
import importlib
import pathlib
import subprocess
import sys

import pytest

from pydomjudge.scripts import _cli, commands


def _leaves(parser: argparse.ArgumentParser, path=()):
    """(command path, parser) of every command that runs something."""
    subparsers = [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    if not subparsers:
        yield path, parser
        return
    for name, sub in subparsers[0].choices.items():
        yield from _leaves(sub, (*path, name))


def test_every_command_runs_an_existing_function():
    for path, leaf in _leaves(commands.build_parser()):
        run = leaf.get_default("_run")
        assert run, f"{' '.join(path)} runs nothing"
        module, function = run.split(":")
        assert callable(getattr(importlib.import_module(module), function)), run


def test_building_the_parser_imports_nothing_heavy():
    code = (
        "import sys\n"
        "from pydomjudge.scripts.commands import build_parser\n"
        "build_parser()\n"
        "heavy = ('problemtools', 'matplotlib', 'flask', 'pydomjudge.repository')\n"
        "print(sorted({m.split('.')[0] for m in sys.modules if m.startswith(heavy)}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"


@pytest.mark.parametrize(
    "argv",
    [
        ["upload", "--db", "x.yml", "settings"],
        ["upload", "settings", "--db", "x.yml"],
    ],
)
def test_shared_options_before_or_after_the_command(argv):
    args = commands.build_parser().parse_args(argv)
    assert args.db == pathlib.Path("x.yml")
    assert args.instance == pathlib.Path("instance.json")
    assert args.upload_command == "settings"


@pytest.mark.parametrize(
    "argv", [["--debug", "problem", "find"], ["problem", "find", "--debug"]]
)
def test_logging_options_before_or_after_the_command(argv):
    args = commands.build_parser().parse_args(argv)
    assert args.debug is True and args.log is None
    assert args.name == [] and args.repository is None


def test_defaults_without_options():
    args = commands.build_parser().parse_args(["upload", "contest", "c.json"])
    assert (args.db, args.repository, args.debug) == (
        pathlib.Path("db.yml"),
        None,
        False,
    )
    assert args.verify and args.update_submissions and args.update_problems
    args = commands.build_parser().parse_args(["serve", "fuzzer"])
    assert args.repository is None and args.port == 5000


def test_problem_key_completion(examples_dir, monkeypatch):
    monkeypatch.chdir(examples_dir)
    assert _cli.problem_key_completer("", argparse.Namespace()) == [
        "dfamin",
        "helloworld",
        "pastryperfection",
    ]
    assert _cli.problem_key_completer("pa", argparse.Namespace()) == [
        "pastryperfection"
    ]
    assert "contest.json" in _cli.json_completer("con")
