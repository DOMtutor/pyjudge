import argparse
import logging

from pydomjudge.exc import error_handler_wrapper
from pydomjudge.model import (
    JudgeSettings,
    JudgingSettings,
    ScoringSettings,
    DisplaySettings,
    ClarificationSettings,
    JudgeInstance,
    DefaultCategory,
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
        base_time=1.5,
        user_whitelist=set(),
        allowed_language_keys=None,
        team_categories=[DefaultCategory.Participants],
    )


@error_handler_wrapper
def main():
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-O",
        "--output",
        type=str,
        help="File output",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()
    with open_file_or_stdout(args.output) as f:
        f.write(make_settings().model_dump_json(indent=2 if args.pretty else None))
