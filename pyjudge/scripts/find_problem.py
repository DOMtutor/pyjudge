#!/usr/bin/env python
import re
import sys
import argparse

from pyjudge.repository.kattis import RepositoryProblem, Repository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", required=False, action='append', help="Keywords to match", default=[])
    parser.add_argument("--name", required=False, action='append', help="Names to match", default=[])
    parser.add_argument("--exclude", required=False, action='append', help="Names to exclude", default=[])
    args = parser.parse_args()

    name_patterns = [re.compile(pattern) for pattern in args.name]
    keyword_patterns = [re.compile(pattern) for pattern in args.keyword]
    exclude_patterns = [re.compile(pattern) for pattern in args.exclude]

    if not name_patterns and not keyword_patterns:
        print("No patterns given")
        sys.exit()

    repository = Repository()
    filtered_problems = []
    for problem in repository.problems.load_all_problems():
        if keyword_patterns and not any(any(pattern.search(keyword) for keyword in problem.keywords)
                                        for pattern in keyword_patterns):
            continue
        if name_patterns and not any(pattern.search(problem.repository_key) for pattern in name_patterns):
            continue
        if any(pattern.match(problem.repository_key) for pattern in exclude_patterns):
            continue
        filtered_problems.append(problem)

    print(f"Found {len(filtered_problems)} problems")
    for problem in sorted(filtered_problems,
                          key=lambda p: (RepositoryProblem.DIFFICULTIES.index(p.difficulty), p.repository_key)):
        print(f"  {problem.repository_key:30s} - {problem.difficulty:20s} - {','.join(problem.keywords)}")
