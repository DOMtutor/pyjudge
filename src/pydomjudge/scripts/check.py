import sys

from pydomjudge.exc import error_handler_wrapper
from pydomjudge.scripts import _cli


@error_handler_wrapper
def main():
    parser = _cli.make_parser(
        "Verify problems with problemtools, or build their statement",
        repository=True,
        problem_filters=True,
    )
    parser.add_argument(
        "--statement", metavar="LANG", help="Build the statement PDF instead"
    )
    args = parser.parse_args()
    _cli.configure_logging(args)

    problems = _cli.find_problems(_cli.load_repository(args), args)
    if not problems:
        sys.exit("No problems found")

    for problem in problems:
        if args.statement:
            problem.generate_problem_text_if_required(args.statement)
        else:
            problem.check()
