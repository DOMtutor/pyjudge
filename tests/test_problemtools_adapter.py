"""Every entry point of the problemtools adapter, against the installed
problemtools: an update that changes the internals it uses fails here."""

import importlib.resources
import logging
import pathlib
import shutil
import subprocess

import pytest

from pydomjudge.repository import _problemtools as pt

ROOT = pathlib.Path(__file__).resolve().parents[1]

needs_pypy3 = pytest.mark.skipif(
    shutil.which("pypy3") is None, reason="problemtools runs Python with pypy3"
)


def _not_generated(directory: str, names: list[str]) -> set[str]:
    """What a fresh checkout does not have: the verification marker, build
    output and the inputs generated from seed files."""
    generated = {".last_verified", "build"}
    return generated | {
        name
        for name in names
        if name.endswith(".in") and f"{name[: -len('.in')]}.seed" in names
    }


@pytest.fixture
def helloworld(examples_dir, tmp_path) -> pathlib.Path:
    """A copy in a repository of its own, as checks and runs write into the
    problem directory; without generated files, like a fresh checkout."""
    repository = tmp_path / "repository"
    (repository / "problems").mkdir(parents=True)
    shutil.copy(examples_dir / "repository" / "config.yaml", repository)
    target = repository / "problems" / "helloworld"
    shutil.copytree(
        examples_dir / "repository" / "problems" / "helloworld",
        target,
        ignore=_not_generated,
    )
    return target


def test_written_against_the_submodule_commit():
    tree = subprocess.run(
        ["git", "-C", str(ROOT), "ls-tree", "HEAD", "libs/problemtools"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    # Update the adapter (and its documentation) together with the submodule
    assert tree[2] == pt.PROBLEMTOOLS_COMMIT


def test_verify_error_is_an_exception():
    assert issubclass(pt.VerifyError, Exception)


def test_fresh_problem_per_with_block(helloworld):
    problem = pt.Problem(helloworld)
    directories = []
    for _ in range(2):
        with problem as loaded:
            assert loaded.tmpdir.is_dir()
            directories.append(loaded.tmpdir)
            submissions = loaded.submissions()
            accepted = submissions["AC"]
            assert [program.name for program in accepted] == ["HelloWorldTobias.py"]
            # copied into this block's directory
            assert accepted[0].path.is_relative_to(loaded.tmpdir)
            assert accepted[0].path.exists()
            assert str(accepted[0]) == "HelloWorldTobias.py"
        assert not directories[-1].exists()
    assert directories[0] != directories[1]


@needs_pypy3
def test_compile_and_run_a_submission(helloworld, tmp_path):
    with pt.Problem(helloworld) as loaded:
        program = loaded.submissions()["AC"][0]
        assert program.compile()[0]
        sample = helloworld / "data" / "sample" / "1.in"
        output = tmp_path / "out"
        assert program.run(sample, output, tmp_path / "err") == 0
        assert output.read_text() == sample.with_suffix(".ans").read_text()


def _case(directory: pathlib.Path, helloworld: pathlib.Path) -> pathlib.Path:
    data = directory / "data"
    data.mkdir(parents=True)
    for suffix in (".in", ".ans"):
        shutil.copy(
            helloworld / "data" / "sample" / f"1{suffix}", data / f"case{suffix}"
        )
    return data / "case.in"


@needs_pypy3
@pytest.mark.parametrize("program_text", ["print('nope')\n", None])
def test_run_test_case(helloworld, tmp_path, program_text):
    sources = tmp_path / "sources"
    sources.mkdir()
    accepted = helloworld / "submissions" / "accepted" / "HelloWorldTobias.py"
    (sources / "main.py").write_text(program_text or accepted.read_text())
    program, language = pt.source_program(sources, None, tmp_path / "compile")
    assert "Py" in language  # detected from the extension
    assert program.compile()[0]

    with pt.Problem(helloworld) as loaded:
        input_file = _case(tmp_path / "fuzzing", helloworld)
        group = loaded.test_group(tmp_path / "fuzzing")
        outcome = loaded.run_test_case(
            group, program, input_file, time_limit=5.0, data_filter="case$"
        )
    assert outcome.verdict == ("AC" if program_text is None else "WA")
    assert outcome.runtime >= 0
    if program_text is not None:
        assert "judgemessage.txt" in (outcome.additional_info or "")


@needs_pypy3
def test_custom_output_validator(helloworld, tmp_path):
    checker = tmp_path / "checker"
    checker.mkdir()
    for name, script in [("build", "true"), ("run", "exit 42  # accepts everything")]:
        (checker / name).write_text(f"#!/bin/sh\n{script}\n")
        (checker / name).chmod(0o755)
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "main.py").write_text("print('anything')\n")
    program, _ = pt.source_program(sources, "python3", tmp_path / "compile")
    program.compile()
    # problemtools uses custom validators of a legacy problem only with this
    with (helloworld / "problem.yaml").open("a") as f:
        f.write("\nvalidation: custom\n")  # the file has no final newline

    with pt.Problem(helloworld) as loaded:
        loaded.use_output_validator(checker, None)
        input_file = _case(tmp_path / "fuzzing", helloworld)
        outcome = loaded.run_test_case(
            loaded.test_group(tmp_path / "fuzzing"),
            program,
            input_file,
            time_limit=5.0,
            data_filter="case$",
        )
    assert outcome.verdict == "AC"


def test_source_program_needs_a_language(tmp_path):
    (tmp_path / "main.unknown").write_text("?")
    with pytest.raises(ValueError, match="detect the language"):
        pt.source_program(tmp_path, None, tmp_path / "compile")


@pytest.mark.skipif(
    not (
        importlib.resources.files("problemtools") / "support" / "checktestdata"
    ).is_file()
    or shutil.which("pypy3") is None,
    reason="needs checktestdata and pypy3",
)
def test_check(helloworld):
    from pydomjudge.repository.kattis import Repository

    # The inputs of seed files are generated by the repository loader
    problem = Repository(helloworld.parents[1]).problems.load_problem("helloworld")
    assert problem.testcases
    assert (helloworld / "data" / "secret" / "large1.in").is_file()
    with pt.Problem(helloworld) as loaded:
        loaded.check()


def test_check_limit_capabilities(caplog):
    with caplog.at_level(logging.WARNING):
        pt.check_limit_capabilities(logging.getLogger("test"))


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="needs LaTeX")
def test_build_statement_pdf(helloworld, tmp_path):
    destination = tmp_path / "statement.pdf"
    pt.build_statement_pdf(helloworld, "en", destination)
    assert destination.read_bytes().startswith(b"%PDF")
