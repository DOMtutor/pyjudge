"""Replace names, logins and times of a contest export by random ones."""

import argparse
import datetime
import pathlib
import random
import string

import pydantic

from pydomjudge.database import ContestDataExport, TeamDto, UserDto
from pydomjudge.exc import (
    InvalidFileFormatError,
    error_handler_wrapper,
    validation_problems,
)
from pydomjudge.scripts import _cli
from pydomjudge.util import default_wordlist, read_str_from, write_str_to


def anonymize(contest: ContestDataExport) -> ContestDataExport:
    """Anonymize users, teams and times. The same export always gives the
    same result, since the randomness is seeded with the contest key."""
    rng = random.Random(contest.description.contest_key)
    time_delta = datetime.timedelta(
        days=rng.randint(0, 31), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
    ).total_seconds()
    word_list = default_wordlist()

    def unique(make, used: set[str]) -> str:
        while (value := make()) in used:
            pass
        used.add(value)
        return value

    used_logins: set[str] = set()
    users: dict[str, UserDto] = {}
    login_mapping: dict[str, str] = {}
    for login in sorted(contest.users):
        new_login = unique(
            lambda: "".join(rng.choices(string.ascii_lowercase, k=12)), used_logins
        )
        login_mapping[login] = new_login
        users[new_login] = UserDto(
            login_name=new_login,
            display_name=" ".join(rng.choices(word_list, k=2)),
            email=f"{new_login}@example.com",
            external_id=new_login,
        )

    used_team_names: set[str] = set()
    teams: dict[str, TeamDto] = {}
    team_mapping: dict[str, str] = {}
    for name in sorted(contest.teams):
        team = contest.teams[name]
        new_name = unique(
            lambda: "_".join(rng.choices(word_list, k=3)), used_team_names
        )
        team_mapping[name] = new_name
        teams[new_name] = team.model_copy(
            update={
                "name": new_name,
                "display_name": "".join(word.title() for word in new_name.split("_")),
                "external_id": new_name,
                "label": None,
                "member_login_names": [
                    login_mapping[login]
                    for login in team.member_login_names
                    if login in login_mapping
                ],
            }
        )

    submissions = [
        submission.model_copy(
            update={
                "team_name": team_mapping[submission.team_name],
                "submission_time": submission.submission_time + time_delta,
            }
        )
        for submission in contest.submissions
    ]
    clarifications = [
        clarification.model_copy(
            update={
                "team_name": team_mapping[clarification.team_name],
                "request_time": clarification.request_time + time_delta,
            }
        )
        for clarification in contest.clarifications
    ]
    description = contest.description
    new_description = description.model_copy(
        update={
            "start": None
            if description.start is None
            else description.start + time_delta,
            "end": None if description.end is None else description.end + time_delta,
        }
    )
    return contest.model_copy(
        update={
            "users": users,
            "teams": teams,
            "submissions": submissions,
            "clarifications": clarifications,
            "description": new_description,
        }
    )


def command_contest(args: argparse.Namespace) -> None:
    destination: pathlib.Path | None = args.destination
    if destination is not None and destination.exists():
        raise FileExistsError(f"Destination {destination} already exists")
    try:
        contest = ContestDataExport.model_validate_json(read_str_from(args.source))
    except pydantic.ValidationError as e:
        raise InvalidFileFormatError(args.source, *validation_problems(e)) from e
    write_str_to(anonymize(contest).model_dump_json(), destination)


@error_handler_wrapper
def main():
    parser = _cli.make_parser("Anonymize exported contest data")

    subparsers = parser.add_subparsers(help="Help for commands", required=True)
    contest_data_parser = subparsers.add_parser("contest", help="Anonymize a contest")
    contest_data_parser.add_argument(
        "source", help="The contest export (from dt_judge_export)", type=pathlib.Path
    )
    contest_data_parser.add_argument(
        "destination",
        help="Destination file (default: stdout if it is a pipe)",
        type=pathlib.Path,
        nargs="?",
    )
    contest_data_parser.set_defaults(func=command_contest)

    arguments = parser.parse_args()
    _cli.configure_logging(arguments)
    arguments.func(arguments)
