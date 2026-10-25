import argparse

from pydomjudge.scripts import _cli


def run(args: argparse.Namespace) -> None:
    """List the problems matching the filters, by difficulty."""
    from pydomjudge.repository.kattis import RepositoryProblem

    filtered_problems = _cli.find_problems(_cli.load_repository(args), args)
    print(f"Found {len(filtered_problems)} problems")
    for problem in sorted(
        filtered_problems,
        key=lambda p: (
            RepositoryProblem.DIFFICULTIES.index(p.difficulty),
            p.repository_key,
        ),
    ):
        print(
            f"  {problem.repository_key:30s} - {problem.difficulty:20s} - "
            f"{','.join(problem.keywords)}"
        )
