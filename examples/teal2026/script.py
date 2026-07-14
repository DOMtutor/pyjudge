import argparse
import datetime
import logging
from zoneinfo import ZoneInfo

import dateutil

from pydomjudge.model import (
    JudgeSettings,
    DefaultCategory,
    Contest,
    ContestProblem,
    JudgeInstance,
    ClarificationSettings,
    DisplaySettings,
    ScoringSettings,
    JudgingSettings,
)
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
        base_time=1,
        user_whitelist=set("python-bot"),
        allowed_language_keys=set(),
        team_categories=[DefaultCategory.Participants],
    )


def make_contest():
    contest_problems = [
        ContestProblem(
            name="A Hello World!", points=4, color="green", problem_key="helloworld"
        ),
        ContestProblem(
            name="B Pastry Perfection",
            points=4,
            color="blue",
            problem_key="pastryperfection",
        ),
        ContestProblem(
            name="C DFA Minimization", points=4, color="yellow", problem_key="dfamin"
        ),
    ]

    tz = ZoneInfo("Europe/Berlin")
    start_time = dateutil.parser.parse("00:00 2026-07-13").replace(tzinfo=tz)
    end_time = dateutil.parser.parse("00:00 2026-08-07").replace(tzinfo=tz)

    return Contest(
        key="teal2026",
        short_name="teal2026",
        name="TEAL 2026 Contest",
        activation_time=start_time - datetime.timedelta(days=7),
        start_time=start_time,
        freeze_time=None,
        end_time=end_time,
        deactivation_time=end_time + datetime.timedelta(days=7),
        problems=contest_problems,
        public_scoreboard=False,
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

    contest = subparsers.add_parser("contest", help="Create contest")
    contest.set_defaults(func=make_contest)

    args = parser.parse_args()
    with open_file_or_stdout(args.output) as f:
        f.write(args.func().model_dump_json(indent=2 if args.pretty else None))
