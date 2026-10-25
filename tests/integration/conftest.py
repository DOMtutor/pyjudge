"""Fixtures for tests against a real DOMjudge, started by tests/integration/run.sh.

Everything here is skipped unless PYJUDGE_IT_URL is set. run.sh sets:
  PYJUDGE_IT_URL    base URL of the domserver, e.g. http://127.0.0.1:18080
  PYJUDGE_IT_DB     database as host:port (user domjudge, password domjudge-it)
  PYJUDGE_IT_JUDGE  1 if a judgehost runs
"""

import datetime
import os
import pathlib
import re
from collections.abc import Iterator

import httpx
import pytest

from pydomjudge.database import Database
from pydomjudge.model import Contest, JudgeInstance
from pydomjudge.repository.kattis import Repository
from pydomjudge.scripts.upload import PyjudgeConfig

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"

URL = os.environ.get("PYJUDGE_IT_URL")
DB = os.environ.get("PYJUDGE_IT_DB", "127.0.0.1:13306")
JUDGE = os.environ.get("PYJUDGE_IT_JUDGE") == "1"

DB_PASSWORD = "domjudge-it"
ADMIN = ("admin", "admin")  # set by the users.json upload with overwrite_passwords
TEAM = ("user", "user")


def pytest_collection_modifyitems(config, items):
    here = pathlib.Path(__file__).parent
    skip = pytest.mark.skip(reason="needs a DOMjudge, see tests/integration/run.sh")
    for item in items:
        if here in item.path.parents:
            item.add_marker(pytest.mark.integration)
            if not URL:
                item.add_marker(skip)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    report = config.stash.get(DRY_RUN_REPORT, None)
    if report:
        terminalreporter.section("second upload: statements executed vs rows changed")
        for line in report:
            terminalreporter.write_line(line)


DRY_RUN_REPORT = pytest.StashKey[list[str]]()


@pytest.fixture(scope="session")
def base_url() -> str:
    assert URL is not None
    return URL.rstrip("/")


@pytest.fixture(scope="session")
def database() -> Database:
    host, port = DB.split(":")
    return Database(
        host=host,
        port=int(port),
        user="domjudge",
        password=DB_PASSWORD,
        database="domjudge",
    )


@pytest.fixture(scope="session")
def pyjudge_config(database: Database) -> PyjudgeConfig:
    return PyjudgeConfig(
        repository=Repository(EXAMPLES / "repository"),
        judge=JudgeInstance.model_validate_json(
            (EXAMPLES / "instance.json").read_text()
        ),
        database=database,
    )


@pytest.fixture(scope="session")
def contest() -> Contest:
    """The example contest, running since an hour, so that all pages show it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "example_script", EXAMPLES / "script.py"
    )
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    contest: Contest = script.make_contest()
    shift = contest.start_time - datetime.datetime.now(contest.start_time.tzinfo)
    shift += datetime.timedelta(hours=1)
    return contest.model_copy(
        update={
            name: getattr(contest, name) - shift
            for name in (
                "activation_time",
                "start_time",
                "end_time",
                "deactivation_time",
            )
        }
    )


def client(base_url: str, **kwargs) -> httpx.Client:
    return httpx.Client(base_url=base_url, follow_redirects=True, timeout=60, **kwargs)


def login(base_url: str, username: str, password: str) -> httpx.Client:
    """A client with a session of the user, through DOMjudge's CSRF-protected form."""
    session = client(base_url)
    page = session.get("/login")
    page.raise_for_status()
    match = re.search(r'name="_csrf_token"\s+value="([^"]+)"', page.text)
    assert match, "no CSRF token on the login page"
    response = session.post(
        "/login",
        data={"_username": username, "_password": password, "_csrf_token": match[1]},
    )
    response.raise_for_status()
    assert "/login" not in str(response.url), f"login of {username} failed"
    return session


@pytest.fixture(scope="module")
def admin(base_url: str, uploaded) -> Iterator[httpx.Client]:
    session = login(base_url, *ADMIN)
    yield session
    session.close()


@pytest.fixture(scope="module")
def team(base_url: str, uploaded) -> Iterator[httpx.Client]:
    session = login(base_url, *TEAM)
    yield session
    session.close()
