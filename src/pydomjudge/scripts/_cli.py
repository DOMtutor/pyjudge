"""Options, logging, completion and configuration loading shared by the tools."""

import argparse
import logging
import pathlib
import re
from typing import TYPE_CHECKING, Any

import pydantic
import yaml

from pydomjudge.database import Database
from pydomjudge.exc import (
    ConfigurationError,
    InvalidFileFormatError,
    UnlikelyInstructionError,
    validation_problems,
)
from pydomjudge.model import Contest, JudgeInstance, SystemCategory

if TYPE_CHECKING:  # importing problemtools is slow, only some tools need it
    from pydomjudge.repository.kattis import Repository, RepositoryProblem


LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def add_logging_options(parser: argparse.ArgumentParser, suppress: bool = False):
    """--debug and --log. With suppress, unset options leave the values of an
    enclosing parser alone, so that they can be given before or after a
    subcommand."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS if suppress else False,
        help="Debug output of pydomjudge and the libraries it uses (problemtools)",
    )
    group.add_argument(
        "--log",
        choices=LOG_LEVELS,
        default=argparse.SUPPRESS if suppress else None,
        help="Log level of pydomjudge (default: INFO)",
    )


def add_shared_options(
    parser: argparse.ArgumentParser,
    *,
    database: bool = False,
    repository: bool = False,
    instance: bool = False,
    problem_filters: bool = False,
    suppress: bool = False,
) -> None:
    """The options several tools share; suppress as in add_logging_options."""

    def default(value):
        return argparse.SUPPRESS if suppress else value

    if database:
        parser.add_argument(
            "--db",
            type=pathlib.Path,
            default=default(None),
            help="Database configuration file (default: from pyjudge.yaml, else db.yml)",
        )
    if repository:
        _action = parser.add_argument(
            "--repository",
            type=pathlib.Path,
            default=default(None),
            help="Problem repository (default: from pyjudge.yaml, else ./repository, "
            "or . and its parents)",
        )
        _complete(_action, directory_completer)
    if instance:
        _action = parser.add_argument(
            "--instance",
            type=pathlib.Path,
            default=default(None),
            help="Judge instance specification (default: from pyjudge.yaml, else "
            "instance.json)",
        )
        _complete(_action, json_completer)
    if problem_filters:
        _action = parser.add_argument(
            "--name",
            action="append",
            default=default([]),
            help="Regex on the problem key",
        )
        _complete(_action, problem_key_completer)
        parser.add_argument(
            "--keyword",
            action="append",
            default=default([]),
            help="Regex on a keyword",
        )
        _action = parser.add_argument(
            "--exclude",
            action="append",
            default=default([]),
            help="Regex on the problem key to exclude",
        )
        _complete(_action, problem_key_completer)
        _action = parser.add_argument(
            "--contest",
            action="append",
            default=default([]),
            type=pathlib.Path,
            help="Only the problems of this contest file",
        )
        _complete(_action, json_completer)


# Shell completion (argcomplete); these must stay cheap, they run on every <Tab>


def _complete(action: argparse.Action, completer) -> None:
    """Attach an argcomplete completer to an option."""
    vars(action)["completer"] = completer  # argparse.Action has no such field


def _repository_candidates(parsed_args) -> list[pathlib.Path]:
    given = getattr(parsed_args, "repository", None)
    cwd = pathlib.Path.cwd()
    if given:
        return [given / "repository", given, given.parent]
    return [cwd / "repository", cwd, *cwd.resolve().parents]


def problem_key_completer(prefix: str, parsed_args=None, **_kwargs) -> list[str]:
    """Problem keys: folders with a problem.yaml in the repository's problems/."""
    for candidate in _repository_candidates(parsed_args):
        problems = candidate / "problems"
        if (candidate / "config.yaml").is_file() and problems.is_dir():
            return sorted(
                path.name
                for path in problems.iterdir()
                if path.name.startswith(prefix) and (path / "problem.yaml").is_file()
            )
    return []


def _path_completer(prefix: str, suffixes: tuple[str, ...], directories_only: bool):
    base = pathlib.Path(prefix).parent if prefix else pathlib.Path(".")
    name_prefix = (
        pathlib.Path(prefix).name if prefix and not prefix.endswith("/") else ""
    )
    if prefix.endswith("/"):
        base = pathlib.Path(prefix)
    try:
        entries = list(base.iterdir())
    except OSError:
        return []
    result = []
    for entry in entries:
        if not entry.name.startswith(name_prefix) or entry.name.startswith("."):
            continue
        shown = str(entry) if str(base) != "." else entry.name
        if entry.is_dir():
            result.append(shown + "/")
        elif not directories_only and entry.name.endswith(suffixes):
            result.append(shown)
    return sorted(result)


def json_completer(prefix: str, **_kwargs) -> list[str]:
    return _path_completer(prefix, (".json", ".json.gz"), directories_only=False)


def directory_completer(prefix: str, **_kwargs) -> list[str]:
    return _path_completer(prefix, (), directories_only=True)


def configure_logging(args: argparse.Namespace) -> None:
    """INFO for pydomjudge (or --log), WARNING for libraries; --debug: all DEBUG."""
    debug = getattr(args, "debug", False)
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    level = "DEBUG" if debug else (getattr(args, "log", None) or "INFO")
    logging.getLogger("pydomjudge").setLevel(level)
    logging.getLogger("problemtools").setLevel(
        logging.DEBUG if debug else logging.WARNING
    )


def setting(args: argparse.Namespace, name: str, option: str | None = None) -> Any:
    """A setting from the command line option or the configuration files
    (see _config); None if neither has it."""
    from pydomjudge.scripts import _config

    value, _source = _config.lookup(name, getattr(args, option or name, None))
    return value


def load_database(args: argparse.Namespace) -> Database:
    from pydomjudge.scripts import _config

    value, source = _config.lookup("database", getattr(args, "db", None))
    if value is None:
        value = pathlib.Path("db.yml")
    if isinstance(value, _config.DatabaseConfig):
        return Database(**value.connection(pathlib.Path(source)))
    path: pathlib.Path = value
    if not path.is_file():
        raise ConfigurationError(
            f"No database configuration found at {path}; create one (pyjudge init), "
            "set --db or 'database:' in pyjudge.yaml"
        )
    try:
        with path.open(mode="rt") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise InvalidFileFormatError(path, f"invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise InvalidFileFormatError(path, "expected a mapping (host, user, ...)")
    try:
        config = _config.DatabaseConfig.model_validate(data)
    except pydantic.ValidationError as e:
        raise InvalidFileFormatError(path, *validation_problems(e)) from e
    return Database(**config.connection(path))


def load_model[M: pydantic.BaseModel](
    path: pathlib.Path, model: type[M], context: Any = None
) -> M:
    """A JSON file as pydantic model; problems are reported with the file."""
    try:
        text = path.read_text()
    except OSError as e:
        raise ConfigurationError(f"{path}: {e.strerror}") from e
    try:
        return model.model_validate_json(text, context=context)
    except pydantic.ValidationError as e:
        raise InvalidFileFormatError(path, *validation_problems(e)) from e


def load_repository(args: argparse.Namespace) -> "Repository":
    from pydomjudge.repository.kattis import Repository

    cwd = pathlib.Path.cwd()
    given: pathlib.Path | None = setting(args, "repository")
    if given is None:
        candidates = [cwd / "repository", cwd, *cwd.resolve().parents]
    else:
        candidates = [given / "repository", given, given.parent]
    for path in candidates:
        if Repository.is_repository(path):
            return Repository(path)
    raise ConfigurationError(
        f"No repository (config.yaml and problems/) at {given if given else cwd}"
    )


def load_instance(args: argparse.Namespace) -> JudgeInstance:
    path: pathlib.Path = setting(args, "instance") or pathlib.Path("instance.json")
    if not path.is_file():
        raise ConfigurationError(
            f"No instance.json found (expected one at {path}). Set the correct path "
            f"with --instance or in pyjudge.yaml, or create one with pyjudge init."
        )
    instance = load_model(path, JudgeInstance)
    if not instance.team_categories:
        raise UnlikelyInstructionError(
            "Instance has no defined categories, this is very likely not what you want"
        )
    category_keys = {category.key for category in instance.team_categories}
    for system_category in SystemCategory.values():
        if system_category.key in category_keys:
            raise ConfigurationError(
                f"Reserved system category {system_category.key} declared!"
            )
    return instance


def find_problems(
    repository: "Repository", args: argparse.Namespace
) -> "list[RepositoryProblem]":
    """The problems selected by the problem filter options."""
    name_patterns = [re.compile(pattern) for pattern in args.name]
    keyword_patterns = [re.compile(pattern) for pattern in args.keyword]
    exclude_patterns = [re.compile(pattern) for pattern in args.exclude]

    candidates: list[RepositoryProblem]
    if args.contest:
        candidates = []
        for contest_file in args.contest:
            contest = load_model(contest_file, Contest)
            for contest_problem in contest.problems:
                problem = repository.problems.load_problem(contest_problem.problem_key)
                if problem not in candidates:
                    candidates.append(problem)
    else:
        candidates = repository.problems.load_all_problems()

    return [
        problem
        for problem in candidates
        if (
            not keyword_patterns
            or any(
                pattern.search(keyword)
                for pattern in keyword_patterns
                for keyword in problem.keywords
            )
        )
        and (
            not name_patterns
            or any(pattern.search(problem.repository_key) for pattern in name_patterns)
        )
        and not any(
            pattern.match(problem.repository_key) for pattern in exclude_patterns
        )
    ]
