"""The self-service app on the test database, checked through DOMjudge's login."""

import concurrent.futures
from collections.abc import Iterator

import httpx
import pytest

from pydomjudge.database import Database
from pydomjudge.model import Contest
from pydomjudge.tools.selfservice._selfservice import (
    REFUSED,
    THROTTLED,
    AppConfig,
    ChangePasswordService,
    RegisterService,
    Services,
    create_app,
)

from .conftest import ADMIN, login

USERNAME = "it_selfservice"


def _delete(database: Database) -> None:
    with database as db, db.transaction_cursor() as cursor:
        cursor.execute("DELETE FROM `user` WHERE username = %s", (USERNAME,))
        cursor.execute("DELETE FROM team WHERE name = %s", (USERNAME,))


@pytest.fixture
def selfservice(database: Database, uploaded: Contest) -> Iterator:
    _delete(database)
    config = AppConfig(
        database=database,
        secret_key="test",
        minimum_password_length=8,
        services=Services(
            register=RegisterService(),
            change_password=ChangePasswordService(attempts=3, address_attempts=10),
        ),
    )
    app = create_app(config)
    app.config["WTF_CSRF_ENABLED"] = False
    yield app.test_client()
    _delete(database)


def _domjudge_login_fails(base_url: str, username: str, password: str) -> bool:
    # DOMjudge answers a failed login with 401 and the login form
    try:
        login(base_url, username, password).close()
    except httpx.HTTPStatusError as e:
        return e.response.status_code == 401
    return False


def _change(client, username: str, current: str, new: str):
    return client.post(
        "/password",
        data={
            "username": username,
            "current_password": current,
            "password": new,
            "password_confirm": new,
        },
    )


def test_register_and_change_password(selfservice, base_url: str):
    response = selfservice.post(
        "/register",
        data={
            "username": USERNAME,
            "password": "first password",
            "password_confirm": "first password",
        },
    )
    assert response.status_code == 302, response.data

    session = login(base_url, USERNAME, "first password")
    try:
        team_page = session.get("/team")
        assert team_page.status_code == 200
        assert "/team" in str(team_page.url)
    finally:
        session.close()

    assert (
        _change(selfservice, USERNAME, "first password", "second password").status_code
        == 302
    )
    assert _domjudge_login_fails(base_url, USERNAME, "first password")
    login(base_url, USERNAME, "second password").close()


def test_change_password_refusals(selfservice, base_url: str):
    # The admin is no team-only user; the answer is the one for a wrong password
    response = _change(selfservice, ADMIN[0], ADMIN[1], "another password")
    assert response.status_code == 400
    assert REFUSED.encode() in response.data
    login(base_url, *ADMIN).close()

    wrong = _change(selfservice, "user", "wrong password", "another password")
    assert REFUSED.encode() in wrong.data
    unknown = _change(selfservice, "nobody_here", "wrong password", "x" * 8)
    assert REFUSED.encode() in unknown.data

    for _ in range(2):
        _change(selfservice, "user", "wrong password", "another password")
    # Throttled even with the right password (user/user from users.json)
    throttled = _change(selfservice, "user", "user", "another password")
    assert throttled.status_code == 429
    assert THROTTLED.encode() in throttled.data
    login(base_url, "user", "user").close()


def test_register_refuses_existing_names(selfservice):
    response = selfservice.post(
        "/register",
        data={"username": "user", "password": "x" * 8, "password_confirm": "x" * 8},
    )
    assert response.status_code == 400
    assert b"already taken" in response.data


def test_startup_checks_category(database: Database, uploaded: Contest):
    config = AppConfig(
        database=database,
        secret_key="test",
        minimum_password_length=8,
        services=Services(register=RegisterService(category="no_such_category")),
    )
    with pytest.raises(Exception, match="no_such_category"):
        create_app(config)


def test_concurrent_registrations(selfservice, database: Database):
    # gunicorn runs the app with several threads sharing one backend
    names = [f"{USERNAME}_{index}" for index in range(8)]

    def register(name: str) -> int:
        return selfservice.post(
            "/register",
            data={"username": name, "password": "x" * 8, "password_confirm": "x" * 8},
        ).status_code

    try:
        with concurrent.futures.ThreadPoolExecutor(len(names)) as pool:
            assert list(pool.map(register, names)) == [302] * len(names)
        with database as db, db.transaction_cursor(readonly=True) as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM team WHERE name LIKE %s", (f"{USERNAME}\\_%",)
            )
            assert cursor.fetchone()[0] == len(names)
    finally:
        with database as db, db.transaction_cursor() as cursor:
            for name in names:
                cursor.execute("DELETE FROM `user` WHERE username = %s", (name,))
                cursor.execute("DELETE FROM team WHERE name = %s", (name,))
