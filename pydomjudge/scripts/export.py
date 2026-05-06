import argparse
import logging
import pathlib
from typing import Optional

from pydantic import BaseModel

import pydomjudge.scripts.db as db
from pydomjudge.action import query
from pydomjudge.data.submission import (
    ContestDataDto,
    SubmissionDto,
)
from pydomjudge.scripts.db import Database
from pydomjudge.util import write_str_to

log = logging.getLogger(__name__)


class SubmissionsExport(BaseModel):
    submissions: list[SubmissionDto]


def fetch_contest(database: Database, contest_key: str):
    with database as connection:
        teams = query.find_non_system_teams(connection)
        teams_by_key = {team.key: team for team in teams}
        language_name_by_key = query.find_languages(connection)

        contest_keys = query.find_contest_keys(connection)
        if contest_key not in contest_keys:
            raise ValueError(
                f"Contest {contest_key} not found, known contests: {' '.join(contest_keys)}"
            )

        contest_description = query.find_contest_description(connection, contest_key)

        contest_problems = query.find_contest_problems(connection, contest_key)
        problem_key_by_contest_problem_key = {
            problem.name: problem.problem_key for problem in contest_problems
        }

        logging.info("Fetching submissions")
        submissions = [
            submission
            for submission in query.find_submissions(connection, contest_key)
            if submission.team_key in teams_by_key
        ]
        logging.info("Fetching clarifications")
        clarifications = [
            clarification
            for clarification in query.find_clarifications(connection, contest_key)
            if clarification.team_key in teams_by_key
        ]
    return ContestDataDto(
        description=contest_description,
        teams=teams_by_key,
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
        teams = query.find_non_system_teams(connection)
        team_keys = {team.key for team in teams}
        submissions = [
            submission
            for submission in query.find_submissions(connection, contest_key)
            if submission.team_key in team_keys
        ]

    write_str_to(
        SubmissionsExport(submissions=submissions).model_dump_json(), destination
    )


def command_contest(database: Database, args):
    write_contest(database, args.contest, args.destination)


def command_submissions(database: Database, args):
    write_submission_files(database, args.contest, args.destination)


def main():
    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser()
    db.make_argparse(parser)

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
    arguments.func(db.from_args(arguments), arguments)
