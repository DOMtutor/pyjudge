"""Fuzzer and self-service web apps, without database and without real fuzzing runs."""

import logging
import pathlib
import threading
import time
import types

import pydantic
import pytest

from pydomjudge.database import Database
from pydomjudge.exc import ConfigurationError, InvalidFileFormatError
from pydomjudge.tools.fuzzer import _fuzzer, create_app as create_fuzzer
from pydomjudge.tools.fuzzer._fuzzer import FuzzingRequest, RunVerdict
from pydomjudge.tools.selfservice._selfservice import (
    REFUSED,
    AppConfig,
    ChangePasswordService,
    PasswordChangeRefused,
    RegisterService,
    Services,
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


def test_fuzzer_lists_languages(fuzzer_client):
    languages = fuzzer_client.get("/languages").get_json()["languages"]
    by_key = {language["key"]: language for language in languages}
    assert set(by_key) == {"c", "java", "python"}
    assert by_key["python"]["name"] == "Python"
    # The usual extension first, the client names the file main.<extension>
    assert by_key["python"]["extensions"][0] == "py"


class _BlockingFuzzer:
    """Reports progress like Fuzzer.run, then waits for the cancel flag."""

    def __init__(self):
        self.cancelled = threading.Event()

    def run(self, request):
        request.progress(1, request.run_count, 1)
        assert request.cancel.wait(10)
        self.cancelled.set()


def test_fuzzer_reports_progress_and_cancels(examples_dir: pathlib.Path):
    app = create_fuzzer(examples_dir / "repository", base_time=1.0)
    fuzzer = _BlockingFuzzer()
    app.extensions["pydomjudge"].fuzzer = fuzzer
    client = app.test_client()

    run_id = client.post("/submission", json=_submission(runs=5)).get_json()["id"]
    deadline = time.monotonic() + 10
    while True:
        state = client.get(f"/submission/{run_id}").get_json()["state"]
        if state["runs_done"] or time.monotonic() > deadline:
            break
        time.sleep(0.01)
    assert (state["runs_done"], state["runs_total"], state["failures"]) == (1, 5, 1)
    assert not state["finished"] and not state["cancelled"]

    # A second run on the problem waits for the first one
    second_id = client.post("/submission", json=_submission()).get_json()["id"]
    while (
        "Waiting"
        not in client.get(f"/submission/{second_id}").get_json()["state"]["log"]
    ):
        assert time.monotonic() < deadline
        time.sleep(0.01)

    state = client.delete(f"/submission/{run_id}").get_json()["state"]
    assert state["cancelled"]
    assert fuzzer.cancelled.wait(10)
    assert not client.get(f"/submission/{run_id}").get_json()["success"]

    # Now the second one runs
    while not client.get(f"/submission/{second_id}").get_json()["state"]["runs_done"]:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    client.delete(f"/submission/{second_id}")


class _FakeRun:
    """Stands in for FuzzingRun: every run fails."""

    runs = 0

    def __init__(self, *args):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def evaluate(self):
        _FakeRun.runs += 1
        return types.SimpleNamespace(verdict=RunVerdict.WRONG_ANSWER)


def test_fuzzer_loop_stops_when_cancelled(monkeypatch, tmp_path):
    monkeypatch.setattr(_fuzzer, "FuzzingRun", _FakeRun)
    monkeypatch.setattr(_fuzzer.Fuzzer, "MAX_FAILS", 100)
    _FakeRun.runs = 0
    progress = []
    request = FuzzingRequest(
        sources={},
        language=None,
        problem=None,  # ty: ignore[invalid-argument-type]
        seed_file=tmp_path / "x.seed",
        logger=logging.getLogger("test"),
        time_limit=1.0,
        run_count=10,
    )

    def report(done, total, failures):
        progress.append((done, total, failures))
        if done == 3:
            request.cancel.set()

    request.progress = report
    results = _fuzzer.Fuzzer._fuzz(request, None, tmp_path)  # ty: ignore[invalid-argument-type]
    assert _FakeRun.runs == 3
    assert len(results) == 3
    assert progress == [(1, 10, 1), (2, 10, 2), (3, 10, 3)]


def test_fuzzer_needs_a_repository(monkeypatch):
    monkeypatch.delenv("PYJUDGE_REPOSITORY", raising=False)
    with pytest.raises(Exception, match="PYJUDGE_REPOSITORY"):
        create_fuzzer()


def _write_config(
    path: pathlib.Path,
    database: str,
    secret: str,
    *extra: str,
    services: str | None = "services: {register: {}}",
) -> pathlib.Path:
    lines = [*extra] if services is None else [services, *extra]
    path.write_text(
        f"{secret}\n"
        "database:\n"
        "  host: 127.0.0.1\n"
        "  user: domjudge\n"
        "  database: domjudge\n"
        f"  {database}\n" + "".join(f"{line}\n" for line in lines)
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
    with pytest.raises(InvalidFileFormatError, match="DB_PW"):
        AppConfig.load(config_file)


def test_selfservice_config_services(tmp_path):
    def load(*extra: str) -> AppConfig:
        path = _write_config(
            tmp_path / "config.yaml",
            "password: pw",
            "secret_key: s",
            *extra,
            services=None,
        )
        return AppConfig.load(path)

    # services is required, with at least one service enabled
    with pytest.raises(InvalidFileFormatError, match="services: Field required"):
        load()
    services = load(
        "services:", "  change_password:", "  register: {category: students}"
    ).services
    assert services.enabled == ["register", "change_password"]
    assert services.registration == RegisterService(category="students")
    assert load("services:", "  change_password: {}").services.enabled == [
        "change_password"
    ]
    for empty in ("services: {register: false}", "services: {}"):
        with pytest.raises(InvalidFileFormatError, match="enable at least one service"):
            load(empty)
    with pytest.raises(InvalidFileFormatError, match="registr"):
        load("services: {registration: {}}")
    with pytest.raises(InvalidFileFormatError, match="password_env"):
        AppConfig.load(
            _write_config(
                tmp_path / "c.yaml", "password_env: X\n  password: y", "secret_key: s"
            )
        )


class _FakeBackend:
    def __init__(self):
        self.created: list[tuple[str, str, str]] = []
        self.passwords = {"carol": "old password"}

    def category_exists(self, key: str) -> bool:
        return key != "missing"

    def create_user(self, username: str, password: str, category: str) -> None:
        if username in {name for name, _, _ in self.created}:
            raise UserAlreadyExistsError
        self.created.append((username, password, category))

    def change_password(self, username: str, current: str, new: str) -> None:
        if self.passwords.get(username) != current:
            raise PasswordChangeRefused
        self.passwords[username] = new


def _selfservice_app(services: Services | None = None):
    config = AppConfig(
        database=Database(host="x", user="x", password="x", database="x"),
        secret_key="test",
        minimum_password_length=8,
        services=Services(register=RegisterService()) if services is None else services,
    )
    backend = _FakeBackend()
    app = create_selfservice(config, backend=backend)
    app.config["WTF_CSRF_ENABLED"] = False
    return app.test_client(), backend


@pytest.fixture
def selfservice():
    return _selfservice_app()


def _register(client, username: str, password: str = "long enough"):
    return client.post(
        "/register",
        data={
            "username": username,
            "password": password,
            "password_confirm": password,
        },
    )


def _change_password(client, username: str, current: str, new: str = "new password"):
    return client.post(
        "/password",
        data={
            "username": username,
            "current_password": current,
            "password": new,
            "password_confirm": new,
        },
    )


def test_selfservice_registers_user(selfservice):
    client, backend = selfservice
    assert client.get("/register").status_code == 200
    response = _register(client, "alice")
    assert response.status_code == 302
    assert backend.created == [("alice", "long enough", "participants")]
    assert b"created successfully" in client.get(response.location).data

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


def test_selfservice_username_pattern():
    client, backend = _selfservice_app(
        Services(register=RegisterService(username_pattern="^ge[0-9]+$"))
    )
    assert _register(client, "alice").status_code == 400
    assert _register(client, "ge123").status_code == 302
    assert [name for name, _, _ in backend.created] == ["ge123"]


def test_selfservice_index_and_disabled_services():
    # One service: the index redirects to it, the other one does not exist
    client, _ = _selfservice_app()
    response = client.get("/")
    assert response.status_code == 302
    assert response.location.endswith("/register")
    assert client.get("/password").status_code == 404

    client, _ = _selfservice_app(Services(change_password=ChangePasswordService()))
    assert client.get("/").location.endswith("/password")
    assert client.get("/register").status_code == 404
    assert _register(client, "alice").status_code == 404

    client, _ = _selfservice_app(
        Services(register=RegisterService(), change_password=ChangePasswordService())
    )
    response = client.get("/")
    assert response.status_code == 200
    assert b'href="/register"' in response.data
    assert b'href="/password"' in response.data


def test_selfservice_startup_checks():
    with pytest.raises(pydantic.ValidationError, match="enable at least one"):
        Services()
    with pytest.raises(ConfigurationError, match="missing"):
        _selfservice_app(Services(register=RegisterService(category="missing")))


def test_selfservice_changes_password():
    client, backend = _selfservice_app(
        Services(change_password=ChangePasswordService(attempts=2, address_attempts=3))
    )
    response = _change_password(client, "carol", "old password")
    assert response.status_code == 302
    assert backend.passwords["carol"] == "new password"
    assert b"has been changed" in client.get(response.location).data

    # Wrong password and unknown user get the same answer
    wrong = _change_password(client, "carol", "old password")
    unknown = _change_password(client, "nobody", "old password")
    assert wrong.status_code == unknown.status_code == 400
    assert REFUSED.encode() in wrong.data and REFUSED.encode() in unknown.data

    # A second failure for carol reaches the per-user limit, even with the
    # right password; the per-address limit then blocks everybody
    assert _change_password(client, "carol", "wrong").status_code == 400
    assert _change_password(client, "carol", "new password").status_code == 429
    assert _change_password(client, "dave", "x").status_code == 429
    assert backend.passwords["carol"] == "new password"
