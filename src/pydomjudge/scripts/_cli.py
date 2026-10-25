"""Options, logging and configuration loading shared by the dt_* tools."""

import argparse
import logging
import pathlib
import re
from typing import TYPE_CHECKING

import yaml

from pydomjudge.database import Database
from pydomjudge.exc import ConfigurationError, UnlikelyInstructionError
from pydomjudge.model import Contest, JudgeInstance, SystemCategory

if TYPE_CHECKING:  # importing problemtools is slow, only some tools need it
    from pydomjudge.repository.kattis import Repository, RepositoryProblem

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def make_parser(
    description: str | None = None,
    *,
    database: bool = False,
    repository: bool = False,
    instance: bool = False,
    problem_filters: bool = False,
) -> argparse.ArgumentParser:
    """A parser with the logging options and the requested shared options."""
    parser = argparse.ArgumentParser(description=description)
    logging_group = parser.add_mutually_exclusive_group()
    logging_group.add_argument(
        "--debug",
        action="store_true",
        help="Debug output of pydomjudge and the libraries it uses (problemtools)",
    )
    logging_group.add_argument(
        "--log", choices=LOG_LEVELS, help="Log level of pydomjudge (default: INFO)"
    )
    if database:
        parser.add_argument(
            "--db",
            type=pathlib.Path,
            default=pathlib.Path("db.yml"),
            help="Database configuration (default: db.yml)",
        )
    if repository:
        parser.add_argument(
            "--repository",
            type=pathlib.Path,
            help="Problem repository (default: ./repository, or . and its parents)",
        )
    if instance:
        parser.add_argument(
            "--instance",
            type=pathlib.Path,
            default=pathlib.Path("instance.json"),
            help="Judge instance specification (default: instance.json)",
        )
    if problem_filters:
        parser.add_argument(
            "--name", action="append", default=[], help="Regex on the problem key"
        )
        parser.add_argument(
            "--keyword", action="append", default=[], help="Regex on a keyword"
        )
        parser.add_argument(
            "--exclude",
            action="append",
            default=[],
            help="Regex on the problem key to exclude",
        )
        parser.add_argument(
            "--contest",
            action="append",
            default=[],
            type=pathlib.Path,
            help="Only the problems of this contest file",
        )
    return parser


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


def load_database(args: argparse.Namespace) -> Database:
    path: pathlib.Path = args.db
    if not path.is_file():
        raise ConfigurationError(
            f"No database configuration found at {path}; create one or set --db"
        )
    with path.open(mode="rt") as f:
        config = yaml.safe_load(f)
    if not isinstance(config, dict):
        raise ConfigurationError(f"{path} does not contain a mapping")
    try:
        return Database(**config)
    except KeyError as e:
        raise ConfigurationError(f"{path} lacks the entry {e}") from e


def load_repository(args: argparse.Namespace) -> "Repository":
    from pydomjudge.repository.kattis import Repository

    cwd = pathlib.Path.cwd()
    given: pathlib.Path | None = args.repository
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
    path: pathlib.Path = args.instance
    if not path.is_file():
        raise ConfigurationError(
            f"No instance.json found (expected one at {path}). Set the correct path "
            f"with --instance or generate one with dt_default_settings."
        )
    instance = JudgeInstance.model_validate_json(path.read_text())
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
            contest = Contest.model_validate_json(contest_file.read_bytes())
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
