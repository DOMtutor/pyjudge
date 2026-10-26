import argparse
import logging
import pathlib

from pydantic import BaseModel

import pydomjudge.database as query
from pydomjudge.database import ContestDataExport, Database, SubmissionDto, TeamDto
from pydomjudge.exc import ElementNotFoundError
from pydomjudge.model import SystemCategory
from pydomjudge.scripts import _cli
from pydomjudge.util import write_str_to

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

        language_name_by_key = query.find_languages(connection)

        log.info("Fetching submissions")
        submissions = query.find_submissions(
            connection, contest_key, teams=teams_by_name
        )
        log.info("Fetching clarifications")
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
    database: Database, contest_key: str, destination: pathlib.Path | None
):
    with database as connection:
        teams = query.find_teams(
            connection, except_categories=list(SystemCategory.values())
        )
        team_keys = {team.name for team in teams}
        submissions = query.find_submissions(connection, contest_key, teams=team_keys)

    write_str_to(
        SubmissionsExport(submissions=submissions).model_dump_json(), destination
    )


def command_contest(database: Database, args: argparse.Namespace) -> None:
    write_contest(database, args.contest, args.destination)


def command_submissions(database: Database, args: argparse.Namespace) -> None:
    write_submission_files(database, args.contest, args.destination)


def run(args: argparse.Namespace) -> None:
    database = _cli.load_database(args)
    if args.export_command == "contest":
        command_contest(database, args)
    else:
        command_submissions(database, args)
