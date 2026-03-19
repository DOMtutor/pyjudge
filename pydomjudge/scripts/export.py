from pydantic import BaseModel
import argparse
import logging
import pathlib
import sys
from collections import defaultdict
from typing import Optional

from pydomjudge.action import query
from pydomjudge.data.submission import (
    ContestDataDto,
    SubmissionDto,
    ContestDescriptionDto,
)
import pydomjudge.scripts.db as db
from pydomjudge.data.teams import TeamDto
from pydomjudge.scripts.db import Database
from pydomjudge.util import write_str_to

log = logging.getLogger(__name__)


class SubmissionsExport(BaseModel):
    submissions: list[SubmissionDto]


class SubmissionMetadata(BaseModel):
    # [list(submission_file.parts) for submission_file in paths],
    files: list[pathlib.Path]
    data: SubmissionDto  # exclude_files_if_present=True


class TeamMetadata(BaseModel):
    submissions: list[SubmissionMetadata]


class ProblemMetadata(BaseModel):
    team_data: dict[str, TeamMetadata]


class MetadataExport(BaseModel):
    contest: ContestDescriptionDto
    submissions: dict[str, ProblemMetadata]
    teams: list[TeamDto]


def write_contest(
    database: Database, contest_key: str, destination: pathlib.Path | None
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

    write_str_to(
        ContestDataDto(
            description=contest_description,
            teams=teams_by_key,
            languages=language_name_by_key,
            problems=problem_key_by_contest_problem_key,
            submissions=submissions,
            clarifications=clarifications,
        ).model_dump_json(),
        destination,
    )


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


def write_submissions_folder(
    database: Database, contest_key: str, destination: pathlib.Path
):
    if destination.exists():
        sys.exit("Destination already exists, refusing to export")

    with database as connection:
        contest: ContestDescriptionDto = query.find_contest_description(
            connection, contest_key
        )
        teams = query.find_non_system_teams(connection)
        team_keys = {team.key for team in teams}
        logging.info("Fetching submissions")
        submissions: list[SubmissionDto] = [
            submission
            for submission in query.find_submissions(connection, contest_key)
            if submission.team_key in team_keys
        ]

    log.info("Found %d submissions", len(submissions))
    grouped_submissions = defaultdict(list)
    for submission in submissions:
        grouped_submissions[
            (
                submission.contest_problem_key,
                submission.problem_key,
                submission.team_key,
            )
        ].append(submission)

    submission_metadata: dict[str, dict[str, list[SubmissionMetadata]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for (
        contest_problem_key,
        problem_key,
        team_key,
    ), submissions in grouped_submissions.items():
        path = (
            destination
            / f"{contest_problem_key}_{problem_key}".replace("/", "_")
            / team_key.replace("/", "_")
        )
        path.mkdir(exist_ok=True, parents=True)
        for i, submission in enumerate(
            sorted(submissions, key=lambda s: s.submission_time)
        ):
            paths = []
            for file in submission.files:
                file_destination = path / f"{i:03d}_{file.filename}"
                file_destination.write_bytes(file.content)
                paths.append(file_destination.relative_to(destination))

            submission_metadata[problem_key][team_key].append(
                SubmissionMetadata(
                    files=paths,
                    data=submission,
                )
            )

    write_str_to(
        MetadataExport(
            contest=contest,
            submissions={
                problem_key: ProblemMetadata(
                    team_data={
                        team_key: TeamMetadata(submissions=metadata)
                        for team_key, metadata in submissions_by_team.items()
                    }
                )
                for problem_key, submissions_by_team in submission_metadata.items()
            },
            teams=teams,
        ).model_dump_json(),
        destination / "metadata.json",
    )


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
        "submission_files", help="All submitted files of a contest, written to disk"
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
