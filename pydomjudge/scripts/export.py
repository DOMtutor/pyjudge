import argparse
import json
import logging
import pathlib
import sys
import gzip
from collections import defaultdict
from typing import Optional

from pydomjudge.action import query
from pydomjudge.data.submission import ContestDataDto
import pydomjudge.scripts.db as db
from pydomjudge.scripts.db import Database

log = logging.getLogger(__name__)


def _write_to(data, destination: Optional[pathlib.Path]):
    if destination is None:
        json.dump(data, sys.stdout)
    else:
        if destination.suffix in {".gz", ".gzip"}:
            with gzip.open(str(destination), mode="wt") as f:
                json.dump(data, f)
        else:
            with destination.open(mode="wt") as f:
                json.dump(data, f)


def write_contest(
    database: Database, contest_key: str, destination: Optional[pathlib.Path]
):
    with database as connection:
        teams = query.find_non_system_teams(connection)
        teams_by_key = {team.key: team for team in teams}
        language_name_by_key = query.find_languages(connection)

        contest_description = query.find_contest_description(connection, contest_key)

        contest_problems = query.find_contest_problems(connection, contest_key)
        problem_key_by_contest_problem_key = {
            problem.contest_problem_key: problem.problem_key
            for problem in contest_problems
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

    data = ContestDataDto(
        description=contest_description,
        teams=teams_by_key,
        languages=language_name_by_key,
        problems=problem_key_by_contest_problem_key,
        submissions=submissions,
        clarifications=clarifications,
    ).serialize()
    _write_to(data, destination)


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

    data = [submission.serialize() for submission in submissions]
    _write_to(data, destination)


def write_submissions_folder(
    database: Database, contest_key: str, destination: pathlib.Path
):
    if destination.exists():
        sys.exit("Destination already exists, refusing to export")

    with database as connection:
        teams = query.find_non_system_teams(connection)
        team_keys = {team.key for team in teams}
        submissions = [
            submission
            for submission in query.find_submissions(connection, contest_key)
            if submission.team_key in team_keys
        ]

    log.info("Found %d submissions", len(submissions))
    grouped_submissions = defaultdict(list)
    for submission in submissions:
        grouped_submissions[
            (submission.contest_problem_key, submission.team_key)
        ].append(submission)

    for (problem_key, team_key), submissions in grouped_submissions.items():
        path = destination / problem_key / team_key
        path.mkdir(exist_ok=True, parents=True)
        for i, submission in enumerate(
            sorted(submissions, key=lambda s: s.submission_time)
        ):
            for file in submission.files:
                (path / f"{i:03d}_{file.filename}").write_bytes(file.content)


def command_contest(database: Database, args):
    write_contest(database, args.contest, args.destination)


def command_submissions(database: Database, args):
    write_submission_files(database, args.contest, args.destination)


def command_files(database: Database, args):
    write_submissions_folder(database, args.contest, args.destination)


def main():
    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser()
    db.make_argparse(parser)

    subparsers = parser.add_subparsers(help="Help for commands")
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
    file_export_parser = subparsers.add_parser(
        "files", help="All submitted files of a contest, written to disk"
    )
    file_export_parser.add_argument("contest", help="The contest key")
    file_export_parser.add_argument(
        "-d",
        "--destination",
        help="Destination base folder",
        type=pathlib.Path,
        required=True,
    )
    file_export_parser.set_defaults(func=command_files)

    arguments = parser.parse_args()
    arguments.func(db.from_args(arguments), arguments)
