import argparse
import pathlib
import re
import json
from typing import List

import pyjudge.repository.kattis as kattis
import pyjudge.scripts.util as script_util
from pyjudge.model import Contest
from pyjudge.repository.kattis import RepositoryProblem


def add_arguments(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--keyword",
        required=False,
        action="append",
        help="Keywords to match",
        default=[],
    )
    parser.add_argument(
        "--name", required=False, action="append", help="Names to match", default=[]
    )
    parser.add_argument(
        "--exclude",
        required=False,
        action="append",
        help="Names to exclude",
        default=[],
    )
    parser.add_argument(
        "--contest",
        required=False,
        action="append",
        type=pathlib.Path,
        help="Contests to include",
    )


def find_problems(
    repository: kattis.Repository, args: argparse.Namespace
) -> List[RepositoryProblem]:
    name_patterns = [re.compile(pattern) for pattern in args.name]
    keyword_patterns = [re.compile(pattern) for pattern in args.keyword]
    exclude_patterns = [re.compile(pattern) for pattern in args.exclude]

    problem_candidates = set()
    if args.contest:
        for contest_file in args.contest:
            with contest_file.open(mode="rt") as f:
                contest_data = json.load(f)
            contest = Contest.parse(contest_data, problem_loader=repository.problems)
            for contest_problem in contest.problems:
                problem_candidates.add(contest_problem.problem)
    else:
        problem_candidates = repository.problems.load_all_problems()

    filtered_problems = []
    for problem in problem_candidates:
        if keyword_patterns and not any(
            any(pattern.search(keyword) for keyword in problem.keywords)
            for pattern in keyword_patterns
        ):
            continue
        if name_patterns and not any(
            pattern.search(problem.repository_key) for pattern in name_patterns
        ):
            continue
        if any(pattern.match(problem.repository_key) for pattern in exclude_patterns):
            continue
        filtered_problems.append(problem)
    return filtered_problems


def main():
    parser = argparse.ArgumentParser()
    script_util.add_logging(parser)
    kattis.add_arguments(parser)

    args = parser.parse_args()
    script_util.apply_logging(args)
    repository = kattis.from_args(args)
    filtered_problems = find_problems(repository, args)

    print(f"Found {len(filtered_problems)} problems")
    for problem in sorted(
        filtered_problems,
        key=lambda p: (
            RepositoryProblem.DIFFICULTIES.index(p.difficulty),
            p.repository_key,
        ),
    ):
        print(
            f"  {problem.repository_key:30s} - {problem.difficulty:20s} - {','.join(problem.keywords)}"
        )
