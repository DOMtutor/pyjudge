import argparse
import pathlib
import sys

import pydomjudge.repository.kattis as kattis
import pydomjudge.scripts.util as script_util
import pydomjudge.scripts.find_problem as find_problem


def func_statements(args, problems, add_entry):
    languages = set(args.language)
    for problem in problems:
        for language in languages:
            problem_pdf = problem.generate_problem_text_if_required(language)
            name = f"{problem.name}.pdf"
            if len(languages) > 1:
                add_entry(problem_pdf, f"{language}/{name}")
            else:
                add_entry(problem_pdf, name)


def func_samples(args, problems, add_entry):
    for problem in problems:
        for case in problem.testcases:
            if case.is_sample():
                name = case.unique_name
                if name.startswith("sample/"):
                    name = name[len("sample/") :]

                add_entry(case.input, f"{problem.key}/{name}.in")
                add_entry(case.output, f"{problem.key}/{name}.ans")


def main():
    parser = argparse.ArgumentParser()
    script_util.add_logging(parser)
    kattis.add_arguments(parser)
    find_problem.add_arguments(parser)

    parser.add_argument(
        "destination",
        type=pathlib.Path,
        help="Folder or .tar/.zip file to write the statements to",
    )

    subparsers = parser.add_subparsers()

    statements_parser = subparsers.add_parser("problems")
    statements_parser.add_argument("--language", action="append", default=["en"])
    statements_parser.add_argument("--force", action="store_true")
    statements_parser.set_defaults(func=func_statements)

    samples_parser = subparsers.add_parser("samples")
    samples_parser.set_defaults(func=func_samples)

    args = parser.parse_args()

    script_util.apply_logging(args)
    repository = kattis.from_args(args)
    problems = find_problem.find_problems(repository, args)
    if not problems:
        sys.exit("No problems found")

    destination: pathlib.Path = args.destination
    if destination.suffix == ".tar":
        import tarfile

        with destination.open("wb") as f:
            with tarfile.open(mode="w", fileobj=f) as tar:

                def add_file(data, name):
                    tar.add(data, name, recursive=False)

                args.func(args, problems, add_file)
    elif destination.suffix == ".zip":
        import zipfile

        with destination.open("wb") as f:
            with zipfile.ZipFile(f, mode="w") as z:

                def add_file(data, name):
                    if isinstance(data, bytes):
                        with z.open(name, mode="w") as d:
                            d.write(data)
                    else:
                        z.write(data, name)

                args.func(args, problems, add_file)
    else:
        import shutil

        destination.mkdir(parents=True, exist_ok=True)

        def add_file(data, name):
            shutil.copy(data, destination / name)

        args.func(args, problems, add_file)
