import pytest

from pydomjudge.database._db import (
    DatabaseTransactionCursor,
    field_in_list,
    field_not_in_list,
    get_scalar,
    list_param,
)
from pydomjudge.database._update import (
    DbTestCase,
    jury_submission_external_id,
    test_case_compare_key as compare_key,
)
from pydomjudge.exc import ElementNotFoundError, MultipleElementsFoundError


def test_list_param():
    assert list_param([1, 2, 3]) == "(%s,%s,%s)"


def test_field_in_list_empty_never_matches():
    assert field_in_list("x", []) == "1 = 2"
    assert field_in_list("x", [1]) == "x IN (%s)"


def test_field_not_in_list_empty_always_matches():
    assert field_not_in_list("x", []) == "1 = 1"


def _case(name: str) -> DbTestCase:
    return DbTestCase(
        case_id=0, name=name, description=None, rank=0, input_md5="", output_md5=""
    )


@pytest.mark.parametrize(
    "names",
    [
        ["sample/1", "secret/small_1", "secret/medium_1", "secret/large_1"],
        ["sample/2", "secret/tiny_1", "secret/special_1", "secret/zzz"],
    ],
)
def test_test_case_sort_order(names: list[str]):
    cases = [_case(name) for name in reversed(names)]
    assert [c.name for c in sorted(cases, key=compare_key)] == names


class _FakeCursor:
    """Implements the DBCursor protocol over fixed result rows."""

    rowcount = 0
    lastrowid = None
    arraysize = 1
    description = None

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.executed: list[str] = []

    def execute(self, query, params=None):
        self.executed.append(query)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchmany(self, size=1):
        return self.rows[:size]

    def fetchall(self):
        return list(self.rows)

    def close(self):
        pass

    def __iter__(self):
        return iter(self.rows)


class _FakeConnection:
    def __init__(self):
        self.cursors: list[_FakeCursor] = []
        self.committed = self.rolled_back = 0

    def cursor(self):
        self.cursors.append(_FakeCursor())
        return self.cursors[-1]

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


def test_get_scalar():
    assert get_scalar(_FakeCursor([(1,)])) == 1
    with pytest.raises(ElementNotFoundError):
        get_scalar(_FakeCursor([]))
    with pytest.raises(MultipleElementsFoundError):
        get_scalar(_FakeCursor([(1,), (2,)]))


@pytest.mark.parametrize("readonly", [True, False])
def test_transaction_cursor_readonly(readonly: bool):
    connection = _FakeConnection()
    with DatabaseTransactionCursor(connection, readonly=readonly) as cursor:  # ty: ignore[invalid-argument-type]
        cursor.execute("SELECT 1")
    executed = connection.cursors[0].executed
    assert executed[0] == ("START TRANSACTION READ ONLY" if readonly else "SELECT 1")
    assert connection.committed == 1


def test_transaction_cursor_rolls_back_on_error():
    connection = _FakeConnection()
    with pytest.raises(RuntimeError):
        with DatabaseTransactionCursor(connection):  # ty: ignore[invalid-argument-type]
            raise RuntimeError
    assert (connection.committed, connection.rolled_back) == (0, 1)


def test_jury_submission_external_id_fits_domjudge():
    ids = {jury_submission_external_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(len(external_id) <= 64 for external_id in ids)


class _RowsCursor:
    """Records statements and answers each with the next canned rows."""

    def __init__(self, *answers: list[tuple]):
        self.statements: list[tuple[str, tuple]] = []
        self.answers = list(answers)
        self.rows: list[tuple] = []

    def execute(self, query, params=None):
        self.statements.append((" ".join(query.split()), tuple(params or ())))
        self.rows = self.answers.pop(0)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


def _rows_cursor(*answers: list[tuple]):
    from typing import cast

    from pydomjudge.database._db import DBCursor

    cursor = _RowsCursor(*answers)
    return cursor, cast(DBCursor, cursor)


def test_find_user_and_team_id_match_key_or_name():
    from pydomjudge.database import find_team_id, find_user_id

    cursor, db_cursor = _rows_cursor([(4,)], [])
    assert find_user_id(db_cursor, key="alice", login_name="ali") == 4
    assert find_team_id(db_cursor, name="t_alice") is None
    (user_query, user_params), (team_query, team_params) = cursor.statements
    assert "externalid = %s OR username = %s" in user_query
    assert user_params == ("alice", "ali")
    assert "externalid = %s OR name = %s" in team_query
    assert team_params == (None, "t_alice")
