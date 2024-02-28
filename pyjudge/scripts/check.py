import argparse
import sys

import pyjudge.repository.kattis as kattis
import pyjudge.scripts.util as script_util
import pyjudge.scripts.find_problem as find_problem


def main():
    parser = argparse.ArgumentParser()
    script_util.add_logging(parser)
    kattis.add_arguments(parser)
    find_problem.add_arguments(parser)

    parser.add_argument("--statement", type=str)
    args = parser.parse_args()
    script_util.apply_logging(args)

    repository = kattis.from_args(args)
    problems = find_problem.find_problems(repository, args)
    if not problems:
        sys.exit("No problems found")

    for problem in problems:
        problem.check()
        if args.statement:
            problem.generate_problem_text_if_required(args.statement)
