import argparse
import dataclasses
import datetime
import getpass
import itertools
import logging
import pathlib
import re
import sys
from collections.abc import Collection

from pydantic import BaseModel, field_serializer, field_validator
from pydantic_core.core_schema import ValidationInfo

import pydomjudge.database as update
from pydomjudge.database import Database, DBCursor as Cursor
from pydomjudge.exc import (
    ConfigurationError,
    ProblemVerificationError,
    UnlikelyInstructionError,
)
from pydomjudge.model import (
    Affiliation,
    Contest,
    JudgeInstance,
    ProblemSubmission,
    SystemCategory,
    Team,
    TeamCategory,
    User,
    Verdict,
)
from pydomjudge.repository._problemtools import VerifyError
from pydomjudge.repository.kattis import JurySubmission, Repository, RepositoryProblem
from pydomjudge.scripts import _cli

log = logging.getLogger(__name__)


@dataclasses.dataclass
class PyjudgeConfig:
    repository: Repository
    judge: JudgeInstance
    database: Database


def _update_problem_submissions(
    cursor: Cursor,
    problem: RepositoryProblem,
    config: Repository,
    contest_ids: Collection[int] | None = None,
):
    problem_submissions: Collection[JurySubmission] = problem.submissions
    submissions: list[tuple[Team, ProblemSubmission]] = []
    for submission in sorted(problem_submissions, key=lambda s: s.path):
        language = submission.language
        if language is None:
            log.warning("Did not find a language for submission %s", submission)
            continue

        submission_expected_results: tuple[Verdict, ...] = tuple(
            submission.expected_results
        )
        if set(submission_expected_results) == {Verdict.CORRECT}:
            submissions.append(
                ((config.get_solution_team_of_language(language)), submission)
            )

        author = submission.author
        if author is None:
            log.debug("No author found for submission %s", submission)
        submissions.append((config.get_team_of_author(author), submission))

    teams = set(team for team, _ in submissions)
    affiliations = set(
        team.affiliation for team in teams if team.affiliation is not None
    )
    users: set[User] = set()
    for team in teams:
        users.update(set(member for member in team.members))

    affiliation_ids = update.create_or_update_affiliations(cursor, affiliations)
    user_ids = update.create_or_update_users(cursor, users)
    team_ids = update.create_or_update_teams(cursor, teams, affiliation_ids, user_ids)

    update.create_problem_submissions(
        cursor, problem, submissions, team_ids, contest_ids
    )


def upload_contest(
    config: PyjudgeConfig,
    contest: Contest,
    force=False,
    update_problems=True,
    verify_problems=True,
    update_submissions=True,
    update_test_cases=True,
):
    if not force and contest.is_running(datetime.datetime.now().astimezone()):
        raise UnlikelyInstructionError(
            f"Contest {contest.key} is running; use --force to update it anyway"
        )
    if contest.end_time < datetime.datetime.now(datetime.UTC):
        log.warning(
            "Contest is in the past (ends at %s), is this correct?", contest.end_time
        )
    repository = config.repository
    problems_by_key = {
        contest_problem.problem_key: repository.problems.load_problem(
            contest_problem.problem_key
        )
        for contest_problem in contest.problems
    }

    if update_problems:
        if verify_problems:
            verify(problems_by_key.values())
        else:
            log.info("Skipping problem verification")

    with config.database as connection:
        with connection.transaction_cursor() as cursor:
            contest_id = update.create_or_update_contest(cursor, contest, force=force)

        if update_problems:
            problem_ids: dict[str, int] = {}
            for contest_problem in contest.problems:
                with connection.transaction_cursor() as cursor:
                    problem_ids[contest_problem.problem_key] = (
                        update.create_or_update_problem_data(
                            cursor,
                            config.judge,
                            problems_by_key[contest_problem.problem_key],
                        )
                    )
                    if update_test_cases:
                        update.create_or_update_problem_testcases(
                            cursor, problems_by_key[contest_problem.problem_key]
                        )

            with connection.transaction_cursor() as cursor:
                update.create_or_update_contest_problems(
                    cursor, contest, contest_id, problem_ids
                )

        if update_submissions:
            for problem in problems_by_key.values():
                assert isinstance(problem, RepositoryProblem)
                with connection.transaction_cursor() as cursor:
                    _update_problem_submissions(
                        cursor, problem, config.repository, [contest_id]
                    )

    log.info("Updated contest %s", contest)


def verify(problems: Collection[RepositoryProblem]):
    log.info("Checking problems")
    for problem in problems:
        try:
            problem.check()
        except VerifyError as e:
            raise ProblemVerificationError(
                f"Verification of {problem.repository_key} failed: {e} "
                f"(details with pyjudge problem check --name {problem.repository_key} --debug)"
            ) from e


def upload_problems(
    config: PyjudgeConfig,
    problems: list[RepositoryProblem],
    update_submissions: bool = True,
    verify_problems: bool = True,
    update_test_cases: bool = True,
):
    if verify_problems:
        verify(problems)
    else:
        log.info("Skipping verification")

    with config.database as connection:
        for problem in problems:
            with connection.transaction_cursor() as cursor:
                update.create_or_update_problem_data(cursor, config.judge, problem)
                if update_test_cases:
                    update.create_or_update_problem_testcases(cursor, problem)
                if update_submissions:
                    _update_problem_submissions(
                        cursor, problem, config.repository, None
                    )


class UsersDescription(BaseModel, extra="forbid"):
    users: list[User]
    affiliations: list[Affiliation]
    teams: list[Team]

    # In JSON, teams are a map from team name to the team, which refers to its
    # category, affiliation and members by key. Resolving the category keys
    # needs the instance's categories, passed as validation context
    # {"category_by_key": ...}.

    @field_serializer("teams", when_used="json")
    def _serialize_teams(self, teams: list[Team]):
        return {
            team.name: {
                **team.model_dump(mode="json"),
                "category": team.category.key if team.category is not None else None,
                "members": [member.key for member in team.members],
                "affiliation": team.affiliation.key
                if team.affiliation is not None
                else None,
            }
            for team in teams
        }

    @field_validator("teams", mode="before")
    @classmethod
    def _resolve_team_data(cls, value, info: ValidationInfo):
        if isinstance(value, list):
            return value

        if info.context is None or "category_by_key" not in info.context:
            raise ValueError("Teams need the team categories as validation context")
        if "users" not in info.data or "affiliations" not in info.data:
            raise ValueError("Teams cannot be resolved, users or affiliations invalid")
        category_by_key: dict[str, TeamCategory] = info.context["category_by_key"]
        user_by_key: dict[str, User] = {user.key: user for user in info.data["users"]}
        affiliation_by_key: dict[str, Affiliation] = {
            affiliation.key: affiliation for affiliation in info.data["affiliations"]
        }

        def resolve(team_name: str, kind: str, key: str | None, by_key: dict):
            if key is None:
                return None
            if key not in by_key:
                known = ", ".join(sorted(by_key)) or "none"
                raise ValueError(
                    f"Team {team_name}: unknown {kind} {key!r} (known: {known})"
                )
            return by_key[key]

        return [
            {
                **team,
                "name": name,
                "category": resolve(
                    name, "category", team.get("category"), category_by_key
                ),
                "affiliation": resolve(
                    name, "affiliation", team.get("affiliation"), affiliation_by_key
                ),
                "members": [
                    resolve(name, "member", member, user_by_key)
                    for member in team.get("members", [])
                ],
            }
            for name, team in value.items()
        ]


def upload_users(
    config: PyjudgeConfig,
    description: UsersDescription,
    disable_unknown=False,
    overwrite_passwords=False,
):
    with config.database as connection:
        with connection.transaction_cursor() as cursor:
            affiliation_ids = update.create_or_update_affiliations(
                cursor, description.affiliations
            )
            user_ids = update.create_or_update_users(
                cursor, description.users, overwrite_passwords
            )
            update.create_or_update_teams(
                cursor, description.teams, affiliation_ids, user_ids
            )
            if disable_unknown:
                valid_users = set(
                    itertools.chain(
                        [user.login_name for user in description.users],
                        config.judge.user_whitelist,
                    )
                )
                update.disable_unknown_users(cursor, valid_users)


def update_settings(config: PyjudgeConfig):
    with config.database as connection:
        with connection.transaction_cursor() as cursor:
            update.update_settings(cursor, config.judge.settings)
            update.update_categories(cursor, config.judge.team_categories, lazy=False)
            update.set_global_languages(
                cursor, config.repository.languages, config.judge.allowed_language_keys
            )


def check_database(config: PyjudgeConfig):
    with config.database as connection:
        with connection.transaction_cursor() as cursor:
            update.clear_invalid_submissions(cursor)


def _file_setting(args: argparse.Namespace, name: str) -> pathlib.Path:
    path = _cli.setting(args, name)
    if path is None:
        raise ConfigurationError(
            f"No {name} file given (argument or '{name}:' in pyjudge.yaml)"
        )
    return path


def command_problem(config: PyjudgeConfig, args: argparse.Namespace) -> None:
    problems: list[RepositoryProblem] = []
    if args.regex:
        patterns = [re.compile(pattern) for pattern in args.regex]
        # noinspection PyUnresolvedReferences
        for problem in config.repository.problems.load_all_problems():
            if any(pattern.match(problem.repository_key) for pattern in patterns):
                problems.append(problem)
    # noinspection PyUnresolvedReferences
    problems.extend(config.repository.problems.load_problem(name) for name in args.name)
    for contest_json in args.contest:
        contest_json: pathlib.Path
        contest = _cli.load_model(contest_json, Contest)
        for contest_problem in contest.problems:
            # noinspection PyUnresolvedReferences
            problems.append(
                config.repository.problems.load_problem(contest_problem.problem_key)
            )

    if not problems:
        sys.exit("No problems found")
    log.info("Found problems %s", " ".join(problem.name for problem in problems))

    upload_problems(
        config,
        problems,
        verify_problems=args.verify,
        update_submissions=args.update_submissions,
        update_test_cases=args.update_testcases,
    )


def command_contest(config: PyjudgeConfig, args: argparse.Namespace) -> None:
    upload_contest(
        config,
        _cli.load_model(_file_setting(args, "contest"), Contest),
        force=args.force,
        update_problems=args.update_problems,
        verify_problems=args.verify,
        update_submissions=args.update_submissions,
        update_test_cases=args.update_testcases,
    )


def command_users(config: PyjudgeConfig, args: argparse.Namespace) -> None:
    description = _cli.load_model(
        _file_setting(args, "users"),
        UsersDescription,
        context={
            "category_by_key": {
                category.key: category
                for category in config.judge.team_categories + [SystemCategory.Jury]
            }
        },
    )

    if not args.overwrite_passwords and any(
        user.password_hash for user in description.users
    ):
        log.info("Password hashes specified but not instructed to overwrite passwords")
    upload_users(
        config,
        description,
        disable_unknown=args.disable,
        overwrite_passwords=args.overwrite_passwords,
    )


def command_settings(config: PyjudgeConfig, _: argparse.Namespace) -> None:
    update_settings(config)


def command_check(config: PyjudgeConfig, _: argparse.Namespace) -> None:
    check_database(config)


def command_reset_password(config: PyjudgeConfig, args: argparse.Namespace) -> None:
    password = getpass.getpass(f"New password for {args.user}: ")
    if not password:
        sys.exit("Empty password")
    if getpass.getpass("Repeat the password: ") != password:
        sys.exit("Passwords do not match")
    with config.database as connection:
        with connection.transaction_cursor() as cursor:
            update.update_user_password(cursor, args.user, User.hash_password(password))
    log.info("Updated password of %s", args.user)


def run(args: argparse.Namespace) -> None:
    config = PyjudgeConfig(
        repository=_cli.load_repository(args),
        judge=_cli.load_instance(args),
        database=_cli.load_database(args),
    )
    commands = {
        "settings": command_settings,
        "users": command_users,
        "problem": command_problem,
        "contest": command_contest,
        "password": command_reset_password,
        "cleanup": command_check,
    }
    commands[args.upload_command](config, args)
