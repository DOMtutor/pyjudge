import pathlib

import pytest

from pydomjudge.model import SystemCategory, Verdict
from pydomjudge.repository.kattis import Repository, RepositoryProblem


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
