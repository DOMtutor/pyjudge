import pathlib
import re
import sys
import argparse
import logging

from pyjudge.repository.kattis import RepositoryProblem, Repository


def main():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("problemtools").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="Problem name")
    parser.add_argument("--repository", type=pathlib.Path, default=pathlib.Path.cwd())
    args = parser.parse_args()

    repository = Repository(args.repository)
    try:
        problem = repository.problems.load_problem(args.name)
    except KeyError:
        sys.exit(f"No problem with name {args.name} found in {repository}")
    problem.check()
