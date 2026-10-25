"""pyjudge problem new: the scaffold loads, and verifies if problemtools can run."""

import importlib.resources
import pathlib
import shutil

import pytest

from pydomjudge.repository.kattis import Repository
from pydomjudge.scripts import commands, scaffold


def _can_verify(*tools: str) -> bool:
    checktestdata = (
        importlib.resources.files("problemtools") / "support" / "checktestdata"
    )
    return checktestdata.is_file() and all(shutil.which(tool) for tool in tools)


@pytest.fixture
def repository(examples_dir, tmp_path, monkeypatch) -> pathlib.Path:
    base = tmp_path / "repository"
    (base / "problems").mkdir(parents=True)
    shutil.copy(examples_dir / "repository" / "config.yaml", base)
    monkeypatch.chdir(tmp_path)
    return base


def _new(*argv: str) -> None:
    commands.main(["problem", "new", *argv])


def test_scaffold_loads(repository: pathlib.Path):
    _new("addition", "--name", "Addition", "--seeded")
    problem = Repository(repository).problems.load_problem("addition")
    assert problem.name == "Addition"
    assert problem.difficulty == "easy"
    (submission,) = problem.submissions
    assert submission.language is not None and submission.language.key == "python"
    assert submission.author is not None
    assert submission.author.key == "tobias_meggendorfer"  # the only author
    for path in [
        "problem_statement/problem.en.tex",
        "data/sample/1.in",
        "input_validators/addition.ctd",
        "generators/generator.py",
        "data/secret/small_01.seed",
    ]:
        assert (problem.directory / path).is_file(), path


@pytest.mark.skipif(not _can_verify("pypy3"), reason="needs checktestdata and pypy3")
def test_scaffold_verifies(repository: pathlib.Path):
    _new("addition", "--seeded")
    problem = Repository(repository).problems.load_problem("addition")
    problem.check()
    # the seed file became a test case, its answer from the solution
    secret = problem.directory / "data" / "secret"
    assert (secret / "small_01.in").is_file() and (secret / "small_01.ans").is_file()


@pytest.mark.skipif(
    not _can_verify("javac", "java"), reason="needs checktestdata, Java"
)
def test_java_scaffold_verifies(repository: pathlib.Path):
    _new("addj", "--language", "java")
    problem = Repository(repository).problems.load_problem("addj")
    (submission,) = problem.submissions
    assert submission.file_name.endswith(".java")
    problem.check()


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["Bad"], "Invalid problem key 'Bad'"),
        (["ok", "--author", "nobody"], "Unknown author nobody"),
        (["ok", "--language", "cobol"], "No solution template for language cobol"),
        (["helloworld"], "exists already"),
    ],
)
def test_scaffold_errors(repository: pathlib.Path, capsys, argv, message):
    (repository / "problems" / "helloworld").mkdir()
    with pytest.raises(SystemExit):
        _new(*argv)
    assert message in capsys.readouterr().err


TEMPLATE_FILES = {
    "problem/problem_statement/problem.en.tex",
    "problem/data/sample/1.in",
    "problem/data/sample/1.ans",
    "problem/data/secret/negative.in",
    "problem/data/secret/negative.ans",
    "problem/input_validators/KEY.ctd",
    "seeded/generators/generator.py",
    "seeded/data/secret/small.jinja",
    "seeded/data/secret/small_01.seed",
    *(f"solutions/{name}" for name in ["python.py", "c.c", "cpp.cpp", "java.java"]),
}


def test_templates_are_package_resources():
    root = scaffold.templates()
    found = {
        f"{folder}/{relative}"
        for folder in ["problem", "seeded", "solutions"]
        for relative, _ in scaffold.template_files(root / folder)
    }
    assert found == TEMPLATE_FILES
    for language in scaffold.SOLUTIONS:
        assert scaffold.solution_template(language).is_file()


def test_seed_template_stays_literal(repository: pathlib.Path):
    _new("addition", "--seeded", "--language", "java", "--name", "Sum {a}")
    problem = repository / "problems" / "addition"
    assert (problem / "data/secret/small.jinja").read_text() == "{{ seed }}\n1000\n"
    statement = (problem / "problem_statement/problem.en.tex").read_text()
    assert statement.startswith(r"\problemname{Sum {a}}")
    assert "$a + b$" in statement and "@" not in statement
    (solution,) = (problem / "submissions" / "accepted").iterdir()
    assert solution.name == "AdditionTobias_meggendorfer.java"
    assert "public class AdditionTobias_meggendorfer {" in solution.read_text()
