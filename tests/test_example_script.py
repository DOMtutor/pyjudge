"""examples/script.py generates the committed example files; keep both in sync."""

import importlib.util
import json
import types

import pytest

from pydomjudge.model import Contest, JudgeInstance
from pydomjudge.repository.kattis import Repository
from pydomjudge.scripts.upload import UsersDescription


@pytest.fixture(scope="module")
def script(examples_dir) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "example_script", examples_dir / "script.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_instance_matches_script(script, examples_dir):
    committed = JudgeInstance.model_validate_json(
        (examples_dir / "instance.json").read_text()
    )
    assert json.loads(committed.model_dump_json()) == json.loads(
        script.make_settings().model_dump_json()
    )


def test_contest_problems_exist_in_repository(script, examples_dir):
    contest: Contest = script.make_contest()
    assert Contest.model_validate_json(contest.model_dump_json()) == contest
    committed = Contest.model_validate_json((examples_dir / "contest.json").read_text())
    assert committed.problems == contest.problems

    repository = Repository(examples_dir / "repository")
    for contest_problem in contest.problems:
        repository.problems.load_problem(contest_problem.problem_key)


def test_users_roundtrip(script):
    users: UsersDescription = script.make_users()
    assert {user.key for user in users.users} == {"user", "admin"}
    assert json.loads(users.model_dump_json())["teams"]["user_team"]["members"] == [
        "user"
    ]
