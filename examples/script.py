import argparse
import datetime
import logging

import bcrypt
import tzlocal

from pydomjudge.model import (
    JudgeSettings,
    User,
    UserRole,
    Team,
    DefaultCategory,
    SystemCategory,
    Affiliation,
    Contest,
    ContestProblem,
    JudgeInstance,
    ClarificationSettings,
    DisplaySettings,
    ScoringSettings,
    JudgingSettings,
)
from pydomjudge.scripts.upload import UsersDescription
from pydomjudge.util import open_file_or_stdout


def make_settings():
    judge_settings = JudgeSettings(
        judging=JudgingSettings(),
        scoring=ScoringSettings(),
        display=DisplaySettings(),
        clarification=ClarificationSettings(),
    )
    return JudgeInstance(
        identifier="local",
        settings=judge_settings,
        base_time=1.5,
        user_whitelist=set(),
        allowed_language_keys=set(),
        team_categories=[DefaultCategory.Participants],
    )


def make_contest():
    contest_problem = ContestProblem(
        name="helloworld", points=4, color="blue", problem_key="helloworld"
    )

    base_time = datetime.datetime.now(tzlocal.get_localzone()).replace(
        minute=0, second=0, microsecond=0
    )
    return Contest(
        key="sample",
        short_name="sample",
        name="Sample Contest",
        activation_time=base_time,
        start_time=base_time + datetime.timedelta(hours=1),
        freeze_time=None,
        end_time=base_time + datetime.timedelta(days=14),
        deactivation_time=base_time + datetime.timedelta(days=15),
        problems=[contest_problem],
        public_scoreboard=False,
    )


def make_users():
    salt = bcrypt.gensalt()
    affiliation = Affiliation(
        key="foo", short_name="foo", name="Foo University of Bar", country=None
    )

    user = User(
        key="user",
        login_name="user",
        display_name="User",
        email="user@localhost",
        password_hash=bcrypt.hashpw(b"user", salt).decode(),
        role=UserRole.Participant,
    )
    admin = User(
        key="admin",
        login_name="admin",
        display_name="Admin",
        email="admin@localhost",
        password_hash=bcrypt.hashpw(b"admin", salt).decode(),
        role=UserRole.Admin,
    )
    user_team = Team(
        key="user_team",
        name="user_team",
        display_name="Awesome!",
        members=[user],
        category=DefaultCategory.Participants,
        affiliation=affiliation,
    )
    admin_team = Team(
        key="admin_team",
        name="admin_team",
        display_name="Admin",
        members=[admin],
        category=SystemCategory.Jury,
        affiliation=None,
    )

    return UsersDescription(
        users=[user, admin], affiliations=[affiliation], teams=[user_team, admin_team]
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-O",
        "--output",
        help="File output",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")

    subparsers = parser.add_subparsers(help="Help for commands")
    settings = subparsers.add_parser("settings", help="Create settings")
    settings.set_defaults(func=make_settings)

    users = subparsers.add_parser("users", help="Create users")
    users.set_defaults(func=make_users)

    contest = subparsers.add_parser("contest", help="Create contest")
    contest.set_defaults(func=make_contest)

    args = parser.parse_args()
    with open_file_or_stdout(args.output) as f:
        f.write(args.func().model_dump_json(indent=2 if args.pretty else None))
