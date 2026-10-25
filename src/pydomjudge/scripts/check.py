import argparse
import sys

from pydomjudge.scripts import _cli


def run(args: argparse.Namespace) -> None:
    """Verify the selected problems."""
    problems = _cli.find_problems(_cli.load_repository(args), args)
    if not problems:
        sys.exit("No problems found")
    for problem in problems:
        problem.check()
