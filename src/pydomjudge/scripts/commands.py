# PYTHON_ARGCOMPLETE_OK
"""The command line: ``pyjudge <command> ...``.

Building the parsers must stay cheap, since shell completion builds them on
every <Tab>: the commands' modules (and problemtools, Flask, matplotlib) are
only imported when a command runs.
"""

import argparse
import importlib
import pathlib
import sys
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from pydomjudge.exc import error_handler_wrapper
from pydomjudge.scripts import _cli

Options = Callable[[argparse.ArgumentParser], object]


def _leaf(
    parser: argparse.ArgumentParser,
    run: str,
    options: Options | None = None,
    *,
    nested: bool,
    from_group: bool = False,
    database: bool = False,
    repository: bool = False,
    instance: bool = False,
    problem_filters: bool = False,
    **defaults,
) -> argparse.ArgumentParser:
    """A command: its options, the shared ones, and the function that runs it
    ("module:function"). Options an enclosing parser has as well (logging when
    nested, the shared ones when from_group) are suppressed here, so they work
    before and after the command name without overwriting each other."""
    _cli.add_logging_options(parser, suppress=nested)
    _cli.add_shared_options(
        parser,
        database=database,
        repository=repository,
        instance=instance,
        suppress=from_group,
    )
    if problem_filters:
        _cli.add_shared_options(parser, problem_filters=True)
    if options is not None:
        options(parser)
    parser.set_defaults(_run=run, **defaults)
    return parser


def _subcommands(parser: argparse.ArgumentParser, dest: str):
    return parser.add_subparsers(dest=dest, required=True, metavar="COMMAND")


def _file(parser: Any, name: str, help: str, **kwargs) -> None:
    action = parser.add_argument(name, type=pathlib.Path, help=help, **kwargs)
    _cli._complete(action, _cli.json_completer)


# upload


def _skip_options(parser: argparse.ArgumentParser, problems: bool = False) -> None:
    parser.add_argument(
        "--skip-verify",
        action="store_false",
        dest="verify",
        help="Do not verify the problems with problemtools",
    )
    parser.add_argument(
        "--skip-submissions",
        action="store_false",
        dest="update_submissions",
        help="Do not upload the jury solutions",
    )
    parser.add_argument(
        "--skip-testcases",
        action="store_false",
        dest="update_testcases",
        help="Do not update the test cases",
    )
    if problems:
        parser.add_argument(
            "--skip-problems",
            action="store_false",
            dest="update_problems",
            help="Do not update the problems",
        )


def _upload_problem_options(parser: argparse.ArgumentParser) -> None:
    _cli._complete(
        parser.add_argument("--name", nargs="*", default=[], help="Problem keys"),
        _cli.problem_key_completer,
    )
    parser.add_argument(
        "--regex", nargs="*", default=[], help="Regular expressions on the problem key"
    )
    _cli._complete(
        parser.add_argument(
            "--contest",
            nargs="*",
            type=pathlib.Path,
            default=[],
            help="The problems of these contest files",
        ),
        _cli.json_completer,
    )
    _skip_options(parser)


def _upload_contest_options(parser: argparse.ArgumentParser) -> None:
    _file(
        parser,
        "contest",
        "Contest file (default: 'contest:' of pyjudge.yaml)",
        nargs="?",
    )
    parser.add_argument(
        "--force", action="store_true", help="Update the contest even if it is running"
    )
    _skip_options(parser, problems=True)


def _upload_users_options(parser: argparse.ArgumentParser) -> None:
    _file(parser, "users", "Users file (default: 'users:' of pyjudge.yaml)", nargs="?")
    parser.add_argument(
        "--disable",
        action="store_true",
        help="Disable all users not in the file (or the whitelist)",
    )
    parser.add_argument(
        "--overwrite-passwords",
        action="store_true",
        help="Also set the passwords of existing users",
    )


def _upload(parser: argparse.ArgumentParser) -> None:
    _cli.add_shared_options(parser, database=True, repository=True, instance=True)
    commands = _subcommands(parser, "upload_command")
    run = "pydomjudge.scripts.upload:run"
    for name, help, options in [
        ("settings", "Judge settings, team categories and languages", None),
        (
            "users",
            "Users, teams and affiliations of a users file",
            _upload_users_options,
        ),
        ("contest", "A contest and its problems", _upload_contest_options),
        ("problem", "Problems, without a contest", _upload_problem_options),
        (
            "password",
            "Ask for and set a new password of a user",
            lambda p: p.add_argument("user", help="Key (externalid) of the user"),
        ),
        (
            "cleanup",
            "Delete submissions with empty or binary files or without judging",
            None,
        ),
    ]:
        _leaf(
            commands.add_parser(name, help=help, description=help),
            run,
            options,
            nested=True,
            from_group=True,
            database=True,
            repository=True,
            instance=True,
        )


# export, anonymize


def _destination(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-d",
        "--destination",
        type=pathlib.Path,
        help="Output file, .gz compresses (default: stdout, if it is a pipe)",
    )


def _export(parser: argparse.ArgumentParser) -> None:
    _cli.add_shared_options(parser, database=True)
    commands = _subcommands(parser, "export_command")
    for name, help in [
        ("contest", "Everything about a contest: teams, submissions, clarifications"),
        ("submissions", "The submissions of a contest"),
    ]:

        def options(p: argparse.ArgumentParser) -> None:
            p.add_argument("contest", help="Short name of the contest")
            _destination(p)

        _leaf(
            commands.add_parser(name, help=help, description=help),
            "pydomjudge.scripts.export:run",
            options,
            nested=True,
            from_group=True,
            database=True,
        )


def _anonymize_options(parser: argparse.ArgumentParser) -> None:
    _file(parser, "source", "A contest export (pyjudge export contest)")
    _file(
        parser,
        "destination",
        "Output file (default: stdout, if it is a pipe)",
        nargs="?",
    )


# problem


def _statements_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "destination",
        type=pathlib.Path,
        nargs="?",
        help="Folder, .zip or .tar for the PDFs (default: only build them)",
    )
    parser.add_argument(
        "--language",
        action="append",
        help="Statement language, repeatable (default: en)",
    )
    parser.add_argument("--force", action="store_true", help="Rebuild the PDFs")


def _samples_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "destination", type=pathlib.Path, help="Folder, .zip or .tar for the samples"
    )


def _seed_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "content",
        action="append",
        help="Jinja template, or a file containing it (variables: n, seed, random)",
    )
    parser.add_argument(
        "--filename",
        help="Format of the file names, e.g. 'small_{n:02d}.seed' "
        "(default: <template name>_{n:02d}.seed)",
    )
    parser.add_argument("--count", required=True, type=int, help="Number of files")


def _problem(parser: argparse.ArgumentParser) -> None:
    _cli.add_shared_options(parser, repository=True)
    commands = _subcommands(parser, "problem_command")
    for name, help, run, options, filters in [
        (
            "find",
            "List problems with difficulty and keywords",
            "pydomjudge.scripts.find_problem:run",
            None,
            True,
        ),
        (
            "check",
            "Verify problems with problemtools",
            "pydomjudge.scripts.check:run",
            None,
            True,
        ),
        (
            "statements",
            "Build the statement PDFs",
            "pydomjudge.scripts.get:run_statements",
            _statements_options,
            True,
        ),
        (
            "samples",
            "Write the sample inputs and answers",
            "pydomjudge.scripts.get:run_samples",
            _samples_options,
            True,
        ),
        (
            "seed",
            "Generate seed files from a Jinja template",
            "pydomjudge.scripts.generate_seed:run",
            _seed_options,
            False,
        ),
    ]:
        _leaf(
            commands.add_parser(name, help=help, description=help),
            run,
            options,
            nested=True,
            from_group=True,
            repository=True,
            problem_filters=filters,
        )


# serve


def _fuzzer_options(parser: argparse.ArgumentParser) -> None:
    time = parser.add_mutually_exclusive_group()
    time.add_argument(
        "--base-time",
        type=float,
        help="Base time limit in seconds, times the problem's factor (default 1.0)",
    )
    _file(time, "--instance", "Take the base time from this instance.json")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)


def _selfservice_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-c",
        "--config",
        type=pathlib.Path,
        default=pathlib.Path("config.yaml"),
        help="Configuration file (default: config.yaml)",
    )


def _serve(parser: argparse.ArgumentParser) -> None:
    commands = _subcommands(parser, "serve_command")
    help = "Fuzzer web interface (development server)"
    _leaf(
        commands.add_parser("fuzzer", help=help, description=help),
        "pydomjudge.tools.fuzzer._server:run",
        _fuzzer_options,
        nested=True,
        repository=True,
    )
    help = "Self-service registration (development server)"
    _leaf(
        commands.add_parser("selfservice", help=help, description=help),
        "pydomjudge.tools.selfservice._selfservice:run",
        _selfservice_options,
        nested=True,
    )


def build_parser(prog: str = "pyjudge") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Drive DOMjudge from a problem repository and configuration files.",
    )
    try:
        package_version = version("pydomjudge")
    except PackageNotFoundError:
        package_version = "unknown"
    parser.add_argument("--version", action="version", version=package_version)
    _cli.add_logging_options(parser)
    commands = _subcommands(parser, "command")

    def group(name: str, help: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help, description=help)
        _cli.add_logging_options(sub, suppress=True)
        return sub

    _upload(group("upload", "Synchronise files into the DOMjudge database"))
    _export(group("export", "Export contest data from the DOMjudge database"))
    help = "Replace names and times in a contest export by random ones"
    _leaf(
        commands.add_parser("anonymize", help=help, description=help),
        "pydomjudge.scripts.anonymize:run",
        _anonymize_options,
        nested=True,
    )
    _problem(group("problem", "Work with the problems of the repository"))
    help = "Create pyjudge.yaml, db.yml and instance.json here"
    _leaf(
        commands.add_parser("init", help=help, description=help),
        "pydomjudge.scripts.project:run_init",
        lambda p: p.add_argument(
            "--force", action="store_true", help="Overwrite files"
        ),
        nested=True,
    )
    help = "Show the settings and the files they come from"
    _leaf(
        commands.add_parser("config", help=help, description=help),
        "pydomjudge.scripts.project:run_config",
        nested=True,
        database=True,
        repository=True,
        instance=True,
    )
    help = "Interactively write admin.json with one admin user"
    _leaf(
        commands.add_parser("make-admin", help=help, description=help),
        "pydomjudge.scripts.make_admin:run",
        nested=True,
    )
    _serve(group("serve", "Run the fuzzer or the self-service registration"))
    return parser


def _run(parser: argparse.ArgumentParser, argv: list[str] | None = None) -> None:
    try:
        import argcomplete

        argcomplete.autocomplete(parser)
    except ImportError:  # completion is optional
        pass
    args = parser.parse_args(argv)
    _cli.configure_logging(args)
    module, function = args._run.split(":")
    getattr(importlib.import_module(module), function)(args)


@error_handler_wrapper
def main(argv: list[str] | None = None) -> None:
    _run(build_parser(), argv)


if __name__ == "__main__":
    sys.exit(main())
