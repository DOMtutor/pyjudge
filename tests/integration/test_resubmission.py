"""Changing one jury solution and uploading again.

Runs after test_domjudge.py (same database, contest already uploaded) on a
copy of the example repository, so the change does not touch examples/.
"""

import json
import pathlib
import shutil

import pytest

from pydomjudge.database import Database
from pydomjudge.model import Contest
from pydomjudge.repository.kattis import Repository
from pydomjudge.scripts import upload
from pydomjudge.scripts.upload import PyjudgeConfig

from .conftest import ADMIN, EXAMPLES, login

# Only uploaded for its author team (not accepted, so no sample solution team)
CHANGED = "pastryperfection/submissions/time_limit_exceeded/pastry_perfection_tobias_bruteforce.py"

# Tables an upload of one changed jury solution may add rows to
SUBMISSION_TABLES = [
    "submission",
    "submission_file",
    "judging",
    "judgetask",
    "judging_run",
    "queuetask",
]


def _rows(database: Database, query: str, params=()) -> list[tuple]:
    with database as db, db.transaction_cursor(readonly=True) as cursor:
        cursor.execute(query, params)
        return list(cursor.fetchall())


def _counts(database: Database) -> dict[str, int]:
    return {
        table: _rows(database, f"SELECT COUNT(*) FROM `{table}`")[0][0]
        for table in SUBMISSION_TABLES
    }


def _with_fresh_repository(config: PyjudgeConfig, path: pathlib.Path) -> PyjudgeConfig:
    return PyjudgeConfig(
        repository=Repository(path), judge=config.judge, database=config.database
    )


@pytest.fixture(scope="module")
def copied_config(
    tmp_path_factory, pyjudge_config: PyjudgeConfig
) -> tuple[PyjudgeConfig, pathlib.Path]:
    # copytree keeps modification times, so .last_verified stays valid
    target = tmp_path_factory.mktemp("example") / "repository"
    shutil.copytree(EXAMPLES / "repository", target, symlinks=True)
    config = PyjudgeConfig(
        repository=Repository(target),
        judge=pyjudge_config.judge,
        database=pyjudge_config.database,
    )
    return config, target


def test_changed_jury_solution_is_resubmitted(
    copied_config, database: Database, contest: Contest, base_url: str
):
    config, repository = copied_config
    # Same content as uploaded by test_domjudge.py: nothing happens
    upload.upload_contest(config, contest, force=True, verify_problems=False)
    before = _counts(database)
    (old_id,) = [
        row[0]
        for row in _rows(
            database,
            "SELECT s.submitid FROM submission s "
            "JOIN submission_file f ON f.submitid = s.submitid "
            "WHERE f.filename = %s",
            (pathlib.Path(CHANGED).name,),
        )
    ]

    source = repository / "problems" / CHANGED
    source.write_text(source.read_text() + "\n# changed\n")
    # A fresh repository object, like a new dt_judge_upload run: loaded jury
    # solutions cache their checksum
    config = _with_fresh_repository(config, repository)
    upload.upload_contest(config, contest, force=True, verify_problems=False)

    after = _counts(database)
    testcases = _rows(
        database,
        "SELECT COUNT(*) FROM testcase t JOIN problem p ON p.probid = t.probid "
        "WHERE p.externalid = 'pastryperfection' AND NOT t.deleted",
    )[0][0]
    assert {table: after[table] - before[table] for table in SUBMISSION_TABLES} == {
        "submission": 1,
        "submission_file": 1,
        "judging": 1,
        "judgetask": testcases,
        "judging_run": testcases,
        "queuetask": 1,
    }

    columns = (
        "submitid, origsubmitid, cid, teamid, probid, langid, valid, expected_results"
    )
    old, new = _rows(
        database,
        f"SELECT {columns} FROM submission "
        "WHERE submitid = %s OR origsubmitid = %s ORDER BY submitid",
        (old_id, old_id),
    )
    # The new version points to the old one, which is ignored (invalid)
    assert new[1] == old_id
    assert old[2:6] == new[2:6] and old[7] == new[7]
    assert (old[6], new[6]) == (0, 1)
    new_source = _rows(
        database,
        "SELECT sourcecode FROM submission_file WHERE submitid = %s",
        (new[0],),
    )[0][0]
    assert new_source.decode() == source.read_text()

    # The new judging tasks are configured like the ones of the old version
    def task_configs(submission_id: int) -> list[tuple]:
        rows = _rows(
            database,
            "SELECT testcase_id, compile_config, run_config, compare_config "
            "FROM judgetask WHERE submitid = %s ORDER BY testcase_id",
            (submission_id,),
        )
        return [
            (testcase, *(json.loads(config) for config in configs))
            for testcase, *configs in rows
        ]

    assert task_configs(new[0]) == task_configs(old_id)

    # DOMjudge shows both versions and the verifier
    admin = login(base_url, *ADMIN)
    try:
        for url in [
            f"/jury/submissions/{old_id}",
            f"/jury/submissions/{new[0]}",
            "/jury/judging-verifier",
        ]:
            response = admin.get(url)
            assert response.status_code == 200, f"{url}: {response.status_code}"
    finally:
        admin.close()

    # Uploading the changed repository again changes nothing
    config = _with_fresh_repository(config, repository)
    upload.upload_contest(config, contest, force=True, verify_problems=False)
    assert _counts(database) == after
    assert _rows(
        database, "SELECT valid FROM submission WHERE submitid = %s", (old_id,)
    ) == [(0,)]
