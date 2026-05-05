import argparse
import dataclasses
import datetime
import itertools
import json
import logging
import pathlib
import re
import sys
from typing import List, Tuple, Collection, Dict, Set

from pydantic import BaseModel, field_validator, field_serializer
from pydantic_core.core_schema import ValidationInfo

import pydomjudge.action.update as update
import pydomjudge.repository.kattis as kattis
import pydomjudge.scripts.db as db
import pydomjudge.scripts.util as script_util
from problemtools.verifyproblem import VerifyError
from pydomjudge.model import (
    Contest,
    Verdict,
    ProblemSubmission,
    Team,
    User,
    Affiliation,
    TeamCategory,
)
from pydomjudge.model.settings import JudgeInstance
from pydomjudge.model.team import SystemCategory
from pydomjudge.repository.kattis import Repository, RepositoryProblem, JurySubmission
from pydomjudge.scripts.db import DBCursor as Cursor
from pydomjudge.scripts.db import Database

log = logging.getLogger(__name__)


@dataclasses.dataclass
class PyjudgeConfig(object):
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
    submissions: List[Tuple[Team, ProblemSubmission]] = []
    for submission in sorted(problem_submissions, key=lambda s: s.path):
        language = submission.language
        if language is None:
            log.warning("Did not find a language for submission %s", submission)
            continue

        submission_expected_results: Tuple[Verdict, ...] = tuple(
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
    users: Set[User] = set()
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
        raise ValueError("Contest %s is running")
    if contest.end_time < datetime.datetime.now(datetime.UTC):
        log.warning(
            "Contest is in the past (ends at %s), is this correct?", contest.end_time
        )
    repository = config.repository
    problems_by_key = {
        contest_problem.problem_key: repository.problems.load_problem(
            contest_problem.problem
        )
        for contest_problem in contest.problems
    }

    if update_problems:
        if verify_problems:
            log.info("Checking problems")
            try:
                for problem in problems_by_key.values():
                    problem.check()
            except VerifyError as e:
                log.error("Problem verification failed", exc_info=e)
                return
        else:
            log.info("Skipping problem verification")

    with config.database as connection:
        with connection.transaction_cursor() as cursor:
            contest_id = update.create_or_update_contest(cursor, contest, force=force)

        if update_problems:
            problem_ids: Dict[str, int] = {}
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
                            cursor, contest_problem.problem
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


def upload_problems(
    config: PyjudgeConfig,
    problems: List[RepositoryProblem],
    update_submissions: bool = True,
    verify_problems: bool = False,
):
    if update_submissions:
        if verify_problems:
            log.info("Checking problems")
            try:
                for problem in problems:
                    problem.check()
            except VerifyError as e:
                log.error("Problem verification failed", exc_info=e)
                return
            log.info("All ok, uploading")
        else:
            log.info("Skipping verification")

    with config.database as connection:
        for problem in problems:
            with connection.transaction_cursor() as cursor:
                update.create_or_update_problem_data(cursor, config.judge, problem)
                update.create_or_update_problem_testcases(cursor, problem)
                if update_submissions:
                    _update_problem_submissions(
                        cursor, problem, config.repository, None
                    )


class UsersDescription(BaseModel):
    users: list[User]
    affiliations: list[Affiliation]
    teams: list[Team]

    @field_serializer("teams", when_used="json")
    def _serialize_teams(self, teams: list[Team]):
        return {
            team.name: {
                **vars(team),
                "category": team.category.key if team.category is not None else None,
                "members": [member.login_name for member in team.members],
                "affiliation": team.affiliation.short_name
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

        if info.context is None:
            raise ValueError("Context is None")
        category_by_name: Dict[str, TeamCategory] = info.context.get("category_by_name")
        user_by_login: dict[str, User] = {
            user.login_name: user for user in info.data["users"]
        }
        affiliation_by_name: Dict[str, Affiliation] = {
            affiliation.short_name: affiliation
            for affiliation in info.data["affiliations"]
        }
        return [
            {
                **team,
                "name": name,
                "display_name": team["display_name"],
                "category": category_by_name.get(team["category"])
                if "category" in team
                else None,
                "affiliation": affiliation_by_name.get(team["affiliation"])
                if "affiliation" in team
                else None,
                "members": [user_by_login.get(name) for name in team["members"]],
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
            update.set_languages(
                cursor, config.repository.languages, config.judge.allowed_language_keys
            )


def check_database(config: PyjudgeConfig):
    with config.database as connection:
        with connection.transaction_cursor() as cursor:
            update.clear_invalid_submissions(cursor)


def command_problem(config: PyjudgeConfig, args):
    problems: List[RepositoryProblem] = []
    if args.regex:
        patterns = [re.compile(pattern) for pattern in args.regex]
        for problem in config.repository.problems.load_all_problems():
            if any(pattern.match(problem.repository_key) for pattern in patterns):
                problems.append(problem)
    problems.extend(config.repository.problems.load_problem(name) for name in args.name)
    for contest_json in args.contest:
        contest_json: pathlib.Path
        with contest_json.open(mode="rt") as f:
            data = json.load(f)
        contest = Contest.load(data, config.repository.problems)
        problems.extend(contest_problem.problem for contest_problem in contest.problems)

    if not problems:
        sys.exit("No problems found")
    log.info("Found problems %s", " ".join(problem.name for problem in problems))

    upload_problems(
        config,
        problems,
        verify_problems=args.verify,
        update_submissions=args.update_submissions,
    )


def command_contest(config: PyjudgeConfig, args):
    with args.contest.open(mode="rt") as file:
        contest_upload_data = json.load(file)
    upload_contest(
        config,
        Contest.load(contest_upload_data, config.repository.problems),
        force=args.force,
        update_problems=args.update_problems,
        verify_problems=args.verify,
        update_submissions=args.update_submissions,
        update_test_cases=args.update_testcases,
    )


def command_users(config: PyjudgeConfig, args):
    description = UsersDescription.model_validate_json(
        args.users.read_text(),
        context={
            "category_by_name": {
                category.key: category
                for category in config.judge.team_categories
                + [SystemCategory.Jury.value]
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


def command_settings(config: PyjudgeConfig, _):
    update_settings(config)


def command_check(config: PyjudgeConfig, _):
    check_database(config)


def command_reset_password(config: PyjudgeConfig, _):
    raise NotImplementedError()


def main():
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    script_util.add_logging(parser)
    db.make_argparse(parser)
    kattis.add_arguments(parser)
    parser.add_argument(
        "--instance",
        type=pathlib.Path,
        default="instance.json",
        help="Path to instance specification",
    )

    subparsers = parser.add_subparsers(help="Help for commands")
    problem_parser = subparsers.add_parser("problem", help="Upload problems")
    problem_parser.add_argument(
        "--regex", nargs="*", help="Regexes to match problem name", default=[]
    )
    problem_parser.add_argument("--name", nargs="*", help="Problem names", default=[])
    problem_parser.add_argument(
        "--contest",
        nargs="*",
        type=pathlib.Path,
        help="Update problems of contest description",
        default=[],
    )
    problem_parser.add_argument(
        "--skip-verify",
        action="store_false",
        dest="verify",
        help="Skip checking of problems",
        default=True,
    )
    problem_parser.add_argument(
        "--skip-submissions",
        action="store_false",
        dest="update_submissions",
        default=True,
        help="Skip uploading of sample submissions",
    )
    problem_parser.add_argument(
        "--skip-testcases",
        action="store_false",
        dest="update_testcases",
        default=True,
        help="Skip updating of testcases",
    )
    problem_parser.set_defaults(func=command_problem)

    contest_parser = subparsers.add_parser("contest", help="Upload a contest")
    contest_parser.add_argument(
        "contest", type=pathlib.Path, help="Path to contest specification"
    )
    contest_parser.add_argument(
        "--force", action="store_true", help="Force update even if contest is running"
    )
    contest_parser.add_argument(
        "--skip-verify",
        action="store_false",
        dest="verify",
        default=True,
        help="Skip checking of problems",
    )
    contest_parser.add_argument(
        "--skip-submissions",
        action="store_false",
        dest="update_submissions",
        default=True,
        help="Skip uploading of sample submissions",
    )
    contest_parser.add_argument(
        "--skip-problems",
        action="store_false",
        dest="update_problems",
        default=True,
        help="Skip updating the problems",
    )
    contest_parser.add_argument(
        "--skip-testcases",
        action="store_false",
        dest="update_testcases",
        default=True,
        help="Skip updating of testcases",
    )
    contest_parser.set_defaults(func=command_contest)

    users_parser = subparsers.add_parser("users", help="Upload user file")
    users_parser.add_argument(
        "users", type=pathlib.Path, help="Path to user specification"
    )
    users_parser.add_argument(
        "--disable", action="store_true", help="Disable unknown users"
    )
    users_parser.add_argument(
        "--overwrite-passwords",
        action="store_true",
        help="Overwrite given passwords of existing users",
    )
    users_parser.set_defaults(func=command_users)

    reset_password_parser = subparsers.add_parser(
        "password", help="Reset a user's password"
    )
    reset_password_parser.set_defaults(func=command_reset_password)

    settings_parser = subparsers.add_parser("settings", help="Upload settings")
    settings_parser.set_defaults(func=command_settings)

    check_parser = subparsers.add_parser("check", help="Check things")
    check_parser.set_defaults(func=command_check)

    arguments = parser.parse_args()
    script_util.apply_logging(arguments)

    instance = JudgeInstance.model_validate_json(arguments.instance.read_text())
    if not instance.team_categories:
        raise ValueError(
            "Instance has no defined categories, this is very likely not what you want"
        )
    category_keys = set(category.key for category in instance.team_categories)
    for system_category in SystemCategory:
        if system_category.value.key in category_keys:
            raise ValueError(
                f"Reserved system category {system_category.value.key} declared!"
            )

    config = PyjudgeConfig(
        repository=kattis.from_args(arguments),
        judge=instance,
        database=db.from_args(arguments),
    )
    arguments.func(config, arguments)
