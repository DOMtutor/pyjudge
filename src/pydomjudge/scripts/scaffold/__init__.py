"""pyjudge problem new: a minimal problem folder that verifies.

The example task is "add two numbers", so that the folder passes
pyjudge problem check right away and can be adapted step by step. The files
come from this package: problem/ (and seeded/ for --seeded) mirror the problem
folder, solutions/ holds the accepted solution per language. Only @NAME@ in
the statement and @CLASS@ in the Java solution are replaced.
"""

import argparse
import importlib.resources
import re
import uuid
from collections.abc import Iterator
from importlib.resources.abc import Traversable

from pydomjudge.exc import ConfigurationError
from pydomjudge.scripts import _cli

# problemtools requires this for problem folder names
KEY_PATTERN = re.compile(r"^[a-z0-9]+$")

# The languages of solutions/, in the order of preference for the default
SOLUTIONS = ("python", "c", "cpp", "java")

STATEMENT = "problem_statement/problem.en.tex"


def templates() -> Traversable:
    return importlib.resources.files(__name__)


def template_files(folder: Traversable, prefix: str = "") -> Iterator[tuple[str, str]]:
    """The relative paths and contents of the files below folder."""
    for entry in sorted(folder.iterdir(), key=lambda entry: entry.name):
        if entry.is_dir():
            yield from template_files(entry, f"{prefix}{entry.name}/")
        else:
            yield f"{prefix}{entry.name}", entry.read_text()


def solution_template(language: str) -> Traversable:
    (template,) = (
        entry
        for entry in templates().joinpath("solutions").iterdir()
        if entry.name.partition(".")[0] == language
    )
    return template


def run(args: argparse.Namespace) -> None:
    key: str = args.key
    if not KEY_PATTERN.match(key):
        raise ConfigurationError(
            f"Invalid problem key {key!r}: only lower case letters and digits"
        )
    repository = _cli.load_repository(args)
    directory = repository.base_directory / "problems" / key
    if directory.exists():
        raise ConfigurationError(f"{directory} exists already")

    languages = {language.key for language in repository.languages}
    language = args.language or next(
        (name for name in SOLUTIONS if name in languages), None
    )
    if language not in SOLUTIONS:
        raise ConfigurationError(
            f"No solution template for language {language}; "
            f"choose one of {', '.join(SOLUTIONS)} with --language"
        )
    if language not in languages:
        raise ConfigurationError(f"The repository has no language {language}")

    authors = {author.key: author for author in repository.authors}
    author_key = args.author or (next(iter(authors)) if len(authors) == 1 else None)
    if author_key is not None and author_key not in authors:
        raise ConfigurationError(
            f"Unknown author {author_key} (config.yaml has {', '.join(authors)})"
        )
    author = authors.get(author_key) if author_key else None
    name = args.name or key.capitalize()

    files: dict[str, str] = {
        "problem.yaml": (
            f"name: {name}\n"
            + (f"author: {author.name}\n" if author else "")
            + "license: cc by-sa\n"
            "keywords: easy\n"
            "problem_format_version: legacy\n"
            f"uuid: {uuid.uuid4()}\n"
            "limits:\n  time_multiplier: 1\n"
        )
    }
    files.update(template_files(templates().joinpath("problem")))
    if args.seeded:
        files.update(template_files(templates().joinpath("seeded")))
    files[STATEMENT] = files[STATEMENT].replace("@NAME@", name)
    files[f"input_validators/{key}.ctd"] = files.pop("input_validators/KEY.ctd")

    # The author's naming pattern decides which author team a solution goes to
    template = solution_template(language)
    extension = template.name.partition(".")[2]
    content = template.read_text()
    if language == "java":
        stem = key.capitalize() + (author.key.capitalize() if author else "")
        content = content.replace("@CLASS@", stem)
    else:
        stem = f"{key}_{author.key}" if author else key
    files[f"submissions/accepted/{stem}.{extension}"] = content

    for relative, text in files.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    print(f"Created {directory}:")
    for relative in files:
        print(f"  {relative}")
    print(f"Check it with: pyjudge problem check --name '^{key}$'")
