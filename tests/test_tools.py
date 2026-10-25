"""Fuzzer and self-service web apps, without database and without fuzzing runs."""

import pathlib

import pytest

from pydomjudge.database import Database
from pydomjudge.tools.fuzzer import create_app as create_fuzzer
from pydomjudge.tools.selfservice._selfservice import (
    AppConfig,
    UserAlreadyExistsError,
    create_app as create_selfservice,
)


@pytest.fixture(scope="module")
def fuzzer_client(examples_dir: pathlib.Path):
    app = create_fuzzer(examples_dir / "repository", base_time=1.0)
    return app.test_client()


def _submission(**overrides) -> dict:
    body = {
        "problem": "pastryperfection",
        "language": "python",
        "sources": {"main.py": "print('yes')"},
        "case_name": "small_1",
        "runs": 1,
    }
    body.update(overrides)
    return body


def test_fuzzer_lists_problems_with_seeds(fuzzer_client):
    problems = fuzzer_client.get("/problems").get_json()["problems"]
    assert set(problems) == {"helloworld", "pastryperfection", "dfamin"}
    seeds = fuzzer_client.get("/problem/pastryperfection/seeds").get_json()["seeds"]
    assert "small_1" in seeds
    assert not fuzzer_client.get("/problem/nothing/seeds").get_json()["success"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"sources": {"../../etc/passwd": "x"}}, "String should match pattern"),
        ({"sources": {"/tmp/x.py": "x"}}, "String should match pattern"),
        ({"sources": {}}, "at least 1 item"),
        ({"language": "rust"}, "Unknown language rust"),
        ({"problem": "nothing"}, "Unknown problem nothing"),
        ({"case_name": "nothing"}, "has no seed nothing"),
        ({"runs": 0}, "greater than or equal to 1"),
    ],
)
def test_fuzzer_rejects_invalid_requests(fuzzer_client, overrides, message):
    response = fuzzer_client.post("/submission", json=_submission(**overrides))
    data = response.get_json()
    assert not data["success"]
    assert any(message in error for error in data["errors"]), data["errors"]


def test_fuzzer_needs_a_repository(monkeypatch):
    monkeypatch.delenv("PYJUDGE_REPOSITORY", raising=False)
    with pytest.raises(Exception, match="PYJUDGE_REPOSITORY"):
        create_fuzzer()


def _write_config(path: pathlib.Path, database: str, secret: str) -> pathlib.Path:
    path.write_text(
        f"{secret}\n"
        "database:\n"
        "  host: 127.0.0.1\n"
        "  user: domjudge\n"
        "  database: domjudge\n"
        f"  {database}\n"
    )
    return path


def test_selfservice_config_from_environment(tmp_path, monkeypatch):
    config_file = _write_config(
        tmp_path / "config.yaml", "password_env: DB_PW", "secret_key_env: SECRET"
    )
    monkeypatch.setenv("DB_PW", "pw")
    monkeypatch.setenv("SECRET", "s3cret")
    config = AppConfig.load(config_file)
    assert config.database.password == "pw"
    assert config.secret_key == "s3cret"

    monkeypatch.delenv("DB_PW")
    with pytest.raises(ValueError, match="DB_PW"):
        AppConfig.load(config_file)


class _FakeBackend:
    def __init__(self):
        self.created: list[tuple[str, str]] = []

    def create_user(self, username: str, password: str) -> None:
        if username in {name for name, _ in self.created}:
            raise UserAlreadyExistsError
        self.created.append((username, password))


@pytest.fixture
def selfservice():
    config = AppConfig(
        database=Database(host="x", user="x", password="x", database="x"),
        secret_key="test",
        minimum_password_length=8,
    )
    backend = _FakeBackend()
    app = create_selfservice(config, backend=backend)
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client(), backend


def _register(client, username: str, password: str = "long enough"):
    return client.post(
        "/",
        data={
            "username": username,
            "password": password,
            "password_confirm": password,
        },
    )


def test_selfservice_registers_user(selfservice):
    client, backend = selfservice
    assert client.get("/").status_code == 200
    response = _register(client, "alice")
    assert response.status_code == 302
    assert backend.created == [("alice", "long enough")]

    response = _register(client, "alice")
    assert response.status_code == 400
    assert b"already taken" in response.data


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("bad name", "long enough"),
        ("../admin", "long enough"),
        ("x" * 65, "long enough"),
        ("bob", "short"),
    ],
)
def test_selfservice_rejects_invalid_input(selfservice, username, password):
    client, backend = selfservice
    assert _register(client, username, password).status_code == 400
    assert backend.created == []
