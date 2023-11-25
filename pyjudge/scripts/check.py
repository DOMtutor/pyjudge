import argparse
import logging
import pathlib
import sys

from pyjudge.repository.kattis import Repository


def main():
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("problemtools").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="Problem name")
    parser.add_argument("--repository", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--statement", type=str)
    args = parser.parse_args()

    repository = Repository(args.repository)
    try:
        problem = repository.problems.load_problem(args.name)
    except KeyError:
        sys.exit(f"No problem with name {args.name} found in {repository}")
    problem.check()
    if args.statement:
        problem.generate_problem_text_if_required(args.statement)
