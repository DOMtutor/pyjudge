import argparse
import io
import pathlib
import shutil
import sys
import tarfile
import time
import zipfile
from collections.abc import Callable, Generator
from contextlib import contextmanager

from pydomjudge.scripts import _cli

AddContent = Callable[[bytes | pathlib.Path, str], None]


def func_statements(args, problems, add_content: AddContent):
    languages = args.language or ["en"]
    for problem in problems:
        for language in languages:
            problem_pdf = problem.generate_problem_text_if_required(
                language, force=args.force
            )
            name = f"{problem.name}.pdf"
            if len(languages) > 1:
                add_content(problem_pdf, f"{language}/{name}")
            else:
                add_content(problem_pdf, name)


def func_samples(_, problems, add_content: AddContent):
    for problem in problems:
        for case in problem.testcases:
            if case.is_sample():
                name = case.unique_name
                if name.startswith("sample/"):
                    name = name[len("sample/") :]

                add_content(case.input, f"{problem.key}/{name}.in")
                add_content(case.output, f"{problem.key}/{name}.ans")


@contextmanager
def content_writer(destination: pathlib.Path) -> Generator[AddContent, None, None]:
    """Write named files (bytes or a file to copy) to a .tar, .zip or folder."""
    if destination.suffix == ".tar":
        with tarfile.open(destination, mode="w") as tar:

            def add_to_tar(data: bytes | pathlib.Path, name: str):
                if isinstance(data, bytes):
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    info.mtime = int(time.time())
                    tar.addfile(info, io.BytesIO(data))
                else:
                    tar.add(data, name, recursive=False)

            yield add_to_tar
    elif destination.suffix == ".zip":
        with zipfile.ZipFile(destination, mode="w") as z:

            def add_to_zip(data: bytes | pathlib.Path, name: str):
                if isinstance(data, bytes):
                    z.writestr(name, data)
                else:
                    z.write(data, name)

            yield add_to_zip
    else:
        destination.mkdir(parents=True, exist_ok=True)

        def add_to_folder(data: bytes | pathlib.Path, name: str):
            file = destination / name
            file.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, bytes):
                file.write_bytes(data)
            else:
                shutil.copy(data, file)

        yield add_to_folder


def _problems(args: argparse.Namespace):
    problems = _cli.find_problems(_cli.load_repository(args), args)
    if not problems:
        sys.exit("No problems found")
    return problems


def run_statements(args: argparse.Namespace) -> None:
    """Build the statement PDFs; with a destination, also write them there."""
    problems = _problems(args)
    if args.destination is None:
        for problem in problems:
            for language in args.language or ["en"]:
                problem.generate_problem_text_if_required(language, force=args.force)
        return
    with content_writer(args.destination) as add_content:
        func_statements(args, problems, add_content)


def run_samples(args: argparse.Namespace) -> None:
    """Write the sample inputs and answers."""
    problems = _problems(args)
    with content_writer(args.destination) as add_content:
        func_samples(args, problems, add_content)
