import argparse
import logging
import pathlib
from typing import Optional

from pydantic import BaseModel

import pydomjudge.database as query
import pydomjudge.scripts.db as db
from pydomjudge.database import SubmissionDto, ContestDataExport, TeamDto
from pydomjudge.exc import error_handler_wrapper, ElementNotFoundError
from pydomjudge.model import SystemCategory
from pydomjudge.scripts.db import Database
from pydomjudge.util import write_str_to
import pydomjudge.scripts.util as util

log = logging.getLogger(__name__)


class SubmissionsExport(BaseModel):
    submissions: list[SubmissionDto]


def fetch_contest(database: Database, contest_key: str):
    with database as connection:
        contest_keys = query.find_contest_keys(connection)
        if contest_key not in contest_keys:
            raise ElementNotFoundError(
                f"Contest {contest_key} not found, known contests: {' '.join(contest_keys)}"
            )

        contest_description = query.find_contest_description(connection, contest_key)

        contest_problems = query.find_contest_problems(connection, contest_key)
        problem_key_by_contest_problem_key: dict[str, str] = {
            contest_problem.short_name: contest_problem.problem_external_id
            if contest_problem.problem_external_id
            else contest_problem.problem_name
            for contest_problem in contest_problems
        }

        teams = query.find_teams(connection, SystemCategory.values())
        teams_by_name: dict[str, TeamDto] = {team.name: team for team in teams}
        log.info(teams_by_name)

        language_name_by_key = query.find_languages(connection)

        logging.info("Fetching submissions")
        find_submissions = query.find_submissions(connection, contest_key)
        logging.info("Submissions %s", find_submissions)
        logging.info(
            "Submissions %s", [submission.team_name for submission in find_submissions]
        )
        logging.info("Teams %s", teams_by_name)
        submissions = [
            submission
            for submission in find_submissions
            if submission.team_name in teams_by_name
        ]
        logging.info("Fetching clarifications")
        clarifications = [
            clarification
            for clarification in query.find_clarifications(connection, contest_key)
            if clarification.team_name in teams_by_name
        ]

        user_names = set()
        for team in teams:
            user_names.update(set(team.member_login_names))
        users = query.find_users_by_login(connection, user_names)

    return ContestDataExport(
        users={user.login_name: user for user in users},
        description=contest_description,
        teams=teams_by_name,
        languages=language_name_by_key,
        problems=problem_key_by_contest_problem_key,
        submissions=submissions,
        clarifications=clarifications,
    )


def write_contest(
    database: Database, contest_key: str, destination: pathlib.Path | None
):
    write_str_to(fetch_contest(database, contest_key).model_dump_json(), destination)


def write_submission_files(
    database: Database, contest_key: str, destination: Optional[pathlib.Path]
):
    with database as connection:
        teams = query.find_teams(
            connection, except_categories=list(SystemCategory.values())
        )
        team_keys = {team.name for team in teams}
        submissions = [
            submission
            for submission in query.find_submissions(connection, contest_key)
            if submission.team_name in team_keys
        ]

    write_str_to(
        SubmissionsExport(submissions=submissions).model_dump_json(), destination
    )


def command_contest(database: Database, args):
    write_contest(database, args.contest, args.destination)


def command_submissions(database: Database, args):
    write_submission_files(database, args.contest, args.destination)


@error_handler_wrapper
def main():
    parser = argparse.ArgumentParser()
    db.make_argparse(parser)
    util.add_logging(parser)

    subparsers = parser.add_subparsers(help="Help for commands", required=True)
    contest_data_parser = subparsers.add_parser(
        "contest", help="Relevant data of a contest"
    )
    contest_data_parser.add_argument("contest", help="The contest key")
    contest_data_parser.add_argument(
        "-d", "--destination", help="Destination file", type=pathlib.Path, default=None
    )
    contest_data_parser.set_defaults(func=command_contest)
    submissions_parser = subparsers.add_parser(
        "submissions", help="Submissions of a contest"
    )
    submissions_parser.add_argument("contest", help="The contest key")
    submissions_parser.set_defaults(func=command_submissions)
    submissions_parser.add_argument(
        "-d", "--destination", help="Destination file", type=pathlib.Path, default=None
    )

    arguments = parser.parse_args()
    util.apply_logging(arguments)
    arguments.func(db.from_args(arguments), arguments)
