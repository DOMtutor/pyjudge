import datetime
import argparse
import dataclasses
import logging
import pathlib
import random
import string

from pydomjudge.data.submission import ContestDataDto
from pydomjudge.data.teams import TeamDto, UserDto
from pydomjudge.util import read_json_from, write_json_to, default_wordlist


def anonymize(source: pathlib.Path | None, destination: pathlib.Path | None):
    if destination is not None and destination.exists():
        raise ValueError(f"Destination {destination} already exists")

    contest = ContestDataDto.parse(read_json_from(source))
    team_mapping = dict()
    team_names = set()

    rng = random.Random(hash(contest.description.contest_key))
    time_offset = datetime.timedelta(
        days=rng.randint(0, 31), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
    )
    time_delta = time_offset.total_seconds()

    word_list = default_wordlist()
    teams = []
    for key, team in contest.teams.items():
        while True:
            new_name = tuple(rng.choices(word_list, k=3))
            if new_name not in team_names:
                break
        key_name = "_".join(new_name)
        team_mapping[key] = key_name
        display_name = "".join(w.title() for w in new_name)
        user_login = "".join(rng.sample(string.ascii_lowercase + "-_", k=16))
        user_name = " ".join(rng.choices(word_list, k=2))
        teams.append(
            TeamDto(
                key=key_name,
                display_name=display_name,
                category_name=team.category_name,
                members=[UserDto(user_login, user_name, f"{user_name}@example.com")],
            )
        )

    submissions = [
        dataclasses.replace(
            submission,
            team_key=team_mapping[submission.team_key],
            submission_time=submission.submission_time + time_delta,
        )
        for submission in contest.submissions
    ]

    clarifications = [
        dataclasses.replace(
            clarification,
            team_key=team_mapping[clarification.team_key],
            request_time=clarification.request_time + time_delta,
        )
        for clarification in contest.clarifications
    ]

    description = contest.description
    new_description = dataclasses.replace(
        description,
        start=description.start + time_delta if description.start else None,
        end=description.end + time_delta if description.end else None,
    )
    write_json_to(
        dataclasses.replace(
            contest,
            teams={team.key: team for team in teams},
            submissions=submissions,
            clarifications=clarifications,
            description=new_description,
        ).serialize(),
        destination,
    )


def command_contest(args):
    anonymize(args.source, args.destination)


def main():
    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(help="Help for commands")
    contest_data_parser = subparsers.add_parser("contest", help="Anonymize a contest")
    contest_data_parser.add_argument(
        "source", help="The contest export data", type=pathlib.Path
    )
    contest_data_parser.add_argument(
        "destination", help="Destination file", type=pathlib.Path, default=None
    )
    contest_data_parser.set_defaults(func=command_contest)

    arguments = parser.parse_args()
    arguments.func(arguments)


if __name__ == "__main__":
    main()
