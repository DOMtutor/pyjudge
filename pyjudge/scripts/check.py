import argparse
import logging
import pathlib
import sys
from typing import List

from pyjudge.repository.kattis import Repository


def main():
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("problemtools").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="Problem name")
    parser.add_argument("--repository", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--statement", type=str)
    args = parser.parse_args()

    candidates: List[pathlib.Path] = [args.repository, args.repository / "repository", args.repository.parent]
    repository = None
    for path in candidates:
        if path.exists() and Repository.is_repository(path):
            repository = Repository(args.repository)
            break
    if repository is None:
        sys.exit(f"Did not find a repository at path {args.repository}")

    try:
        problem = repository.problems.load_problem(args.name)
    except KeyError:
        sys.exit(f"No problem with name {args.name} found in {repository}")
    problem.check()
    if args.statement:
        problem.generate_problem_text_if_required(args.statement)
