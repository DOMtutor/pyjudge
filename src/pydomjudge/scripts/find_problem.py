from pydomjudge.exc import error_handler_wrapper
from pydomjudge.repository.kattis import RepositoryProblem
from pydomjudge.scripts import _cli


@error_handler_wrapper
def main():
    parser = _cli.make_parser(
        "List problems of the repository", repository=True, problem_filters=True
    )
    args = parser.parse_args()
    _cli.configure_logging(args)
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
