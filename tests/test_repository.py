import os
import pathlib
import shutil

import pytest

from pydomjudge.exc import InvalidFileFormatError
from pydomjudge.model import SystemCategory, Verdict
from pydomjudge.repository.kattis import (
    JurySubmission,
    KattisRepositoryError,
    Repository,
    RepositoryProblem,
    RepositoryTestCase,
)


@pytest.fixture(scope="module")
def repository(examples_dir) -> Repository:
    return Repository(examples_dir / "repository")


def test_is_repository(examples_dir, tmp_path: pathlib.Path):
    assert Repository.is_repository(examples_dir / "repository")
    assert not Repository.is_repository(tmp_path)


def test_languages_from_config(repository: Repository):
    assert {lang.key for lang in repository.languages} == {"c", "java", "python"}
    python = repository.languages_by_extension["py"]
    assert python.compile_script.key == "compile_python"
    names = {file.relative_path[-1] for file in python.compile_script.contents}
    assert {"build", "run"} <= names


def test_default_languages_have_compiler_scripts():
    for key in Repository._default_language_settings():
        files = Repository._get_files_for_default_language(key)
        names = {file.relative_path[-1] for file in files}
        assert {"build", "run"} <= names, key


def test_load_problem(repository: Repository):
    problem = repository.problems.load_problem("helloworld")
    assert isinstance(problem, RepositoryProblem)
    assert problem.name == "Hello World!"
    assert problem.difficulty == "very easy"
    assert "introduction" in problem.keywords
    assert problem.checker is None
    assert problem.limits.time_factor == 1.0
    assert repository.problems["helloworld"] is problem


def test_unknown_problem(repository: Repository):
    with pytest.raises(KeyError):
        repository.problems.load_problem("does-not-exist")


def test_load_all_problems(repository: Repository):
    keys = {problem.repository_key for problem in repository.problems}
    assert {"helloworld", "pastryperfection"} <= keys


def test_submissions_language_author_and_verdict(repository: Repository):
    problem = repository.problems.load_problem("pastryperfection")
    by_name = {s.file_name: s for s in problem.submissions}
    accepted = by_name["pastry_perfection_tobias.py"]
    assert accepted.language is repository.languages_by_extension["py"]
    assert accepted.expected_results == {Verdict.CORRECT}
    assert accepted.author is not None
    assert accepted.author.key == "tobias_meggendorfer"
    slow = by_name["pastry_perfection_tobias_bruteforce.py"]
    assert slow.expected_results == {Verdict.TIME_LIMIT}
    assert slow.name.startswith("TLE/")


def test_author_teams(repository: Repository):
    problem = repository.problems.load_problem("pastryperfection")
    author = next(iter(problem.submissions)).author
    team = repository.get_team_of_author(author)
    assert team.category == SystemCategory.Author
    assert repository.get_team_of_author(None).key == "sol_author_unknown"


@pytest.fixture
def repository_copy(examples_dir, tmp_path: pathlib.Path) -> pathlib.Path:
    """A writable copy of the example repository with only helloworld."""
    base = tmp_path / "repository"
    (base / "problems").mkdir(parents=True)
    shutil.copy(examples_dir / "repository" / "config.yaml", base)
    shutil.copytree(
        examples_dir / "repository" / "problems" / "helloworld",
        base / "problems" / "helloworld",
        ignore=shutil.ignore_patterns("build", ".last_verified", "*.class"),
    )
    return base


def test_every_submission_category_has_a_short_name():
    for verdicts in JurySubmission.EXPECTED_RESULTS.values():
        assert frozenset(verdicts) in JurySubmission.SHORT_NAMES


def test_slow_input_submission_name(repository_copy: pathlib.Path):
    directory = repository_copy / "problems" / "helloworld" / "submissions"
    (directory / "slow_input").mkdir()
    (directory / "slow_input" / "slow_tobias.py").write_text("print()\n")
    (directory / "unexpected").mkdir()
    (directory / "unexpected" / "x.py").write_text("print()\n")
    problem = Repository(repository_copy).problems.load_problem("helloworld")
    by_name = {s.file_name: s for s in problem.submissions}
    slow = by_name["slow_tobias.py"]
    assert slow.name == "SL/slow_tobias.py"
    assert slow.expected_results == {Verdict.CORRECT, Verdict.TIME_LIMIT}
    with pytest.raises(KattisRepositoryError, match="Unknown submission directory"):
        _ = by_name["x.py"].expected_results


def test_compiler_override_uses_language_directory(repository_copy: pathlib.Path):
    for language in ["python", "c"]:
        directory = repository_copy / "compiler" / language
        directory.mkdir(parents=True)
        (directory / "build").write_text(f"# build {language}\n")
        (directory / "run").write_text(f"# run {language}\n")
    repository = Repository(repository_copy)
    python = repository.languages_by_extension["py"]
    contents = {
        tuple(file.relative_path): file.open().read()
        for file in python.compile_script.contents
    }
    assert contents == {("build",): b"# build python\n", ("run",): b"# run python\n"}


def test_testcase_unique_name(repository: Repository):
    problem = repository.problems.load_problem("helloworld")
    sample = RepositoryTestCase(problem.directory / "data" / "sample" / "1")
    assert sample.unique_name == "sample/1"
    assert sample.is_sample()


def test_verification_marker_ignores_build_output(
    repository_copy: pathlib.Path, monkeypatch
):
    import problemtools.run.limit

    class WouldVerify(Exception):
        pass

    def would_verify(*_args, **_kwargs):
        raise WouldVerify

    monkeypatch.setattr(
        problemtools.run.limit, "check_limit_capabilities", would_verify
    )
    problem = Repository(repository_copy).problems.load_problem("helloworld")
    marker = problem.directory / ".last_verified"
    marker.touch()
    past = marker.stat().st_mtime - 10
    for file in problem.directory.rglob("*"):
        if file.is_file() and file != marker:
            os.utime(file, (past, past))

    (problem.directory / "build").mkdir(exist_ok=True)
    (problem.directory / "build" / "problem.en.pdf").write_bytes(b"%PDF")
    problem.check()  # statement output is newer, still verified

    (problem.directory / "problem.yaml").touch()
    with pytest.raises(WouldVerify):
        problem.check()


def test_languages_in_stable_order(repository: Repository):
    keys = [language.key for language in repository.languages]
    assert keys == sorted(keys)


def test_problem_can_be_entered_again(repository: Repository):
    # problemtools copies the submissions into the temporary directory of the
    # "with" block; a second block must not use the removed copies
    problem = repository.problems["pastryperfection"]
    for _ in range(2):
        with problem as loaded:
            reference = problem._reference_submission
            assert reference is not None
            assert reference.path.is_relative_to(loaded.tmpdir)
            assert reference.path.exists()


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ("languages: [c, julia]\n", "unknown language 'julia' .*known: .*python"),
        ("language: [c]\n", "unknown keys language"),
        (
            "languages:\n  c: {name: C, extensions: [c], timefactor: 2}\n",
            "language c: unknown keys timefactor",
        ),
        ("authors:\n  me: {name: Me, basic_regex: me, mail: x}\n", "mail"),
    ],
)
def test_repository_config_errors(repository_copy: pathlib.Path, config, message):
    (repository_copy / "config.yaml").write_text(config)
    with pytest.raises(InvalidFileFormatError, match=message) as error:
        Repository(repository_copy)
    assert error.value.source == repository_copy / "config.yaml"


def test_run_script_sets_domjudge(repository: Repository):
    script = repository.run_script
    assert (script.key, script.executable_type.value) == ("pyjudge_run", "run")
    files = {file.relative_path[-1]: file for file in script.contents}
    assert set(files) == {"build", "run"}
    with files["run"].open() as f:
        assert b"export DOMJUDGE=1" in f.read()


def test_repository_run_script_replaces_the_default(repository_copy: pathlib.Path):
    runscript = repository_copy / "runscript"
    runscript.mkdir()
    (runscript / "run").write_text('#!/bin/sh\nexec "$@"\n')
    script = Repository(repository_copy).run_script
    assert [file.relative_path[-1] for file in script.contents] == ["run"]


def test_run_script_passes_domjudge_to_runguard(repository: Repository, tmp_path):
    import subprocess

    (run,) = [f for f in repository.run_script.contents if f.relative_path[-1] == "run"]
    script = tmp_path / "run"
    with run.open() as f:
        script.write_bytes(f.read())
    runguard = tmp_path / "bin" / "runguard"
    runguard.parent.mkdir()
    runguard.write_text('#!/bin/sh\nfor a; do printf "[%s]\\n" "$a"; done\n')
    runguard.chmod(0o755)
    (tmp_path / "in").write_text("")
    # As testcase_run.sh calls it, with env standing in for "sudo -n"
    subprocess.run(
        ["sh", str(script), str(tmp_path / "in"), str(tmp_path / "out"), "env",
         str(runguard), "--user=a b", "--", "/x/runguard", "x y"],
        check=True,
    )  # fmt: skip
    assert (tmp_path / "out").read_text().splitlines() == [
        "[-V]", "[DOMJUDGE=1]", "[--user=a b]", "[--]", "[/x/runguard]", "[x y]",
    ]  # fmt: skip
    # Without runguard, the program gets it from the environment
    subprocess.run(
        ["sh", str(script), str(tmp_path / "in"), str(tmp_path / "out"), "sh", "-c",
         'echo "$DOMJUDGE"'],
        check=True,
    )  # fmt: skip
    assert (tmp_path / "out").read_text() == "1\n"
