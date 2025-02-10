#!/usr/bin/env python
import math
import sys
import argparse
import pathlib
import re
from typing import Optional, Tuple


def judge_message(judge_msg, feedback_dir):
    try:
        with (feedback_dir / "judgemessage.txt").open("at") as f:
            f.write(judge_msg)
    except IOError as e:
        print(
            f"Failed to write to judgemessage.txt: {e}\nOriginal error: {judge_msg}",
            file=sys.stderr,
        )


def fail_with_message(
    feedback_dir: pathlib.Path,
    team_msg: str,
    judge_msg: str = "",
    diff_position: Optional[Tuple[int, int]] = None,
):
    if judge_msg:
        judge_message(judge_msg, feedback_dir)
    try:
        with (feedback_dir / "teammessage.txt").open(mode="wt") as f:
            f.write(team_msg)
    except IOError as e:
        judge_message(
            f"Failed to write to teammessage.txt: {e}\nTeam feedback: {team_msg}",
            feedback_dir,
        )
    if diff_position:
        judge_pos, team_pos = diff_position
        try:
            with (feedback_dir / "diffposition.txt").open(mode="wt") as f:
                f.write(f"{judge_pos} {team_pos}")
        except IOError as e:
            judge_message(f"Failed to write to diffposition.txt: {e}", feedback_dir)

    sys.exit(43)


def check(args):
    _, ans_file, feedback_dir = (
        args.input_file,
        args.answer_file,
        args.feedback_dir,
    )

    def fail(
        msg="Wrong Answer",
        judge_msg="",
        diff_position: Optional[Tuple[int, int]] = None,
    ):
        fail_with_message(feedback_dir, msg, judge_msg, diff_position)

    try:
        with ans_file.open(mode="rt") as f:
            judge_string = f.read()
    except Exception as e:
        raise fail(msg="Internal error", judge_msg=f"Error: {e}")

    if args.relative_tolerance or args.absolute_tolerance:
        try:
            team_string = sys.stdin.readline()
            if sys.stdin.read():
                raise fail(
                    judge_msg="Trailing output",
                    diff_position=(len(judge_string), len(team_string) + 1),
                )
        except Exception as e:
            raise fail(msg="Internal error", judge_msg=f"Error: {e}")

        try:
            judge_float = float(judge_string)
        except ValueError:
            raise fail(
                msg="Internal error",
                judge_msg=f"Judge answer is not a float: {judge_string}",
            )
        try:
            team_float = float(team_string)
        except ValueError:
            raise fail(
                judge_msg=f"Team answer is not a float: {team_string}",
                diff_position=(0, 0),
            )

        if math.isnan(judge_float) or math.isnan(team_float):
            if not (math.isnan(judge_float) and math.isnan(team_float)):
                raise fail(judge_msg=f"NaN in {team_string} vs. {judge_string}")
        if args.absolute_tolerance:
            if abs(judge_float - team_float) > args.absolute_tolerance:
                raise fail(
                    judge_msg=f"Absolute difference {team_string} vs. {judge_string} too large"
                )
        if args.relative_tolerance:
            if math.isinf(judge_float) or math.isinf(team_float):
                if not (math.isinf(judge_float) and math.isinf(team_float)):
                    raise fail(
                        judge_msg=f"Relative difference {team_string} vs. {judge_string} too large"
                    )
            else:
                if abs(judge_float - team_float) > args.relative_tolerance * abs(
                    judge_float
                ):
                    raise fail(
                        judge_msg=f"Relative difference {team_string} vs. {judge_string} too large"
                    )
    else:
        try:
            team_string = sys.stdin.read()
        except Exception as e:
            raise fail(msg="Internal error", judge_msg=f"Error: {e}")

        if args.strip:
            judge_string = judge_string.strip()
            team_string = team_string.strip()
        if args.skip_space:
            regex = re.compile(r"\s+")
            judge_string = regex.sub(judge_string, " ")
            team_string = regex.sub(team_string, " ")
        if not args.case_sensitive:
            judge_string = judge_string.lower()
            team_string = team_string.lower()

        if judge_string != team_string:
            raise fail()
    sys.exit(42)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "input_file",
        type=pathlib.Path,
        help="Problem input",
    )
    parser.add_argument(
        "answer_file",
        type=pathlib.Path,
        help="Problem answer",
    )
    parser.add_argument(
        "feedback_dir",
        type=pathlib.Path,
        help="Feedback directory",
    )

    parser.add_argument("--case-sensitive", action="store_true")
    parser.add_argument("--strip", action="store_false")
    parser.add_argument("--skip-space", action="store_true")
    parser.add_argument("--relative-tolerance", type=float, default=None)
    parser.add_argument("--absolute-tolerance", type=float, default=None)

    check(parser.parse_args())
