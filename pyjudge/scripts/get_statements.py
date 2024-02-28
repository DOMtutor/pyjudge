import argparse
import pathlib
import sys

import pyjudge.repository.kattis as kattis
import pyjudge.scripts.util as script_util
import pyjudge.scripts.find_problem as find_problem


def main():
    parser = argparse.ArgumentParser()
    script_util.add_logging(parser)
    kattis.add_arguments(parser)
    find_problem.add_arguments(parser)
    parser.add_argument("--language", type=str, default="en")
    parser.add_argument(
        "destination",
        type=pathlib.Path,
        help="Folder or .tar/.zip file to write the statements to",
    )

    args = parser.parse_args()
    script_util.apply_logging(args)
    repository = kattis.from_args(args)
    problems = find_problem.find_problems(repository, args)
    if not problems:
        sys.exit("No problems found")

    def for_each_problem(callback):
        for problem in problems:
            problem_pdf = problem.generate_problem_text_if_required(args.language)
            callback(problem_pdf, f"{problem.name}.pdf")

    destination: pathlib.Path = args.destination
    if destination.suffix == ".tar":
        import tarfile

        with destination.open("wb") as f:
            with tarfile.open(mode="w", fileobj=f) as tar:

                def add_problem(problem_pdf, name):
                    tar.add(problem_pdf, name, recursive=False)

                for_each_problem(add_problem)
    elif destination.suffix == ".zip":
        import zipfile

        with destination.open("wb") as f:
            with zipfile.ZipFile(f, mode="w") as z:

                def add_problem(problem_pdf, name):
                    z.write(problem_pdf, name)

                for_each_problem(add_problem)
    else:
        import shutil

        destination.mkdir(parents=True, exist_ok=True)

        def add_problem(problem_pdf, name):
            shutil.copy(problem_pdf, destination / name)

        for_each_problem(add_problem)
