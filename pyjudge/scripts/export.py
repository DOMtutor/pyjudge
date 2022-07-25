import argparse
import json
import logging
import pathlib
import sys
import gzip
from typing import Optional

from pyjudge.action import query
from pyjudge.judge import JudgeInstance
from pyjudge.model import TeamCategory
from pyjudge.data.submission import ContestDataDto


def write_contest(judge: JudgeInstance, contest_key: str, destination: Optional[pathlib.Path]):
    with judge.database as connection:
        teams = query.find_teams(connection, [TeamCategory.Participants, TeamCategory.Hidden])
        teams_by_key = {team.key: team for team in teams}
        language_name_by_key = query.find_languages(connection)

        contest_description = query.find_contest_description(connection, contest_key)

        contest_problems = query.find_contest_problems(connection, contest_key)
        problem_key_by_contest_problem_key = {problem.contest_problem_key: problem.problem_key
                                              for problem in contest_problems}

        logging.info("Fetching submissions")
        submissions = [submission for submission in query.find_submissions(connection, contest_key)
                       if submission.team_key in teams_by_key]
        logging.info("Fetching clarifications")
        clarifications = [clarification for clarification in query.find_clarifications(connection, contest_key)
                          if clarification.team_key in teams_by_key]

    data = ContestDataDto(
        description=contest_description,
        teams=teams_by_key,
        languages=language_name_by_key,
        problems=problem_key_by_contest_problem_key,
        submissions=submissions,
        clarifications=clarifications
    ).serialize()
    if destination is None:
        json.dump(data, sys.stdout)
    else:
        if destination.suffix in {".gz", ".gzip"}:
            with gzip.open(str(destination), mode="wt") as f:
                json.dump(data, f)
        else:
            with destination.open(mode="wt") as f:
                json.dump(data, f)


def write_submission_files(judge: JudgeInstance, contest_key: str, destination: Optional[pathlib.Path]):
    with judge.database as connection:
        teams = query.find_teams(connection, [TeamCategory.Participants, TeamCategory.Hidden])
        team_keys = {team.key for team in teams}
        submissions = [submission for submission in query.find_submissions(connection, contest_key)
                       if submission.team_key in team_keys]

    data = [submission.serialize() for submission in submissions]
    if destination is None:
        json.dump(data, sys.stdout)
    else:
        with destination.open(mode="wt") as f:
            json.dump(data, f)


def command_contest(judge: JudgeInstance, args):
    write_contest(judge, args.contest, args.destination)


def command_submission_files(judge: JudgeInstance, args):
    write_submission_files(judge, args.contest, args.destination)


def main():
    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=pathlib.Path, required=True, help="Path to database config")
    parser.add_argument("-d", "--destination", help="Destination file", type=pathlib.Path, default=None)

    subparsers = parser.add_subparsers(help="Help for commands")
    contest_data_parser = subparsers.add_parser("contest", help="Relevant data of a contest")
    contest_data_parser.add_argument("contest", help="The contest key")
    contest_data_parser.set_defaults(func=command_contest)
    submission_files_parser = subparsers.add_parser("files", help="Submissions files of a contest")
    submission_files_parser.add_argument("contest", help="The contest key")
    submission_files_parser.set_defaults(func=command_submission_files)

    arguments = parser.parse_args()
    arguments.func(JudgeInstance(arguments.config), arguments)
