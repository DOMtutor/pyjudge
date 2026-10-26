"""Removing things on upload: team members, contest problems; multi-file
submissions in exports and the submission filters. Each test restores the
example setup at its end."""

import uuid

import pytest

from pydomjudge.database import Database, find_contest_problems, find_submissions
from pydomjudge.model import Contest
from pydomjudge.scripts import upload
from pydomjudge.scripts.export import fetch_contest
from pydomjudge.scripts.upload import PyjudgeConfig

from .conftest import ADMIN, TEAM, client, users_description


def _scalar(database: Database, query: str, *params):
    with database as db, db.transaction_cursor(readonly=True) as cursor:
        cursor.execute(query, params)
        row = cursor.fetchone()
        return None if row is None else row[0]


def _user_team(database: Database) -> str | None:
    return _scalar(
        database,
        "SELECT t.externalid FROM `user` u LEFT JOIN team t ON t.teamid = u.teamid "
        "WHERE u.externalid = 'user'",
    )


def _contest_problems(database: Database, contest: Contest) -> set[str]:
    with database as db, db.transaction_cursor(readonly=True) as cursor:
        cursor.execute(
            "SELECT p.externalid FROM contestproblem cp "
            "JOIN problem p ON p.probid = cp.probid "
            "JOIN contest c ON c.cid = cp.cid WHERE c.externalid = %s",
            (contest.key,),
        )
        return {key for (key,) in cursor.fetchall()}


def _submit(base_url: str, problem: str, files: dict[str, bytes]) -> str:
    """A submission of the team user through the API, its id."""
    with client(base_url, auth=TEAM) as api:
        contest_id = api.get("/api/v4/contests").json()[0]["id"]
        response = api.post(
            f"/api/v4/contests/{contest_id}/submissions",
            data={"problem": problem, "language": "python"},
            files=[("code[]", (name, content)) for name, content in files.items()],
        )
        assert response.status_code == 200, response.text
        return response.json()["id"]


def _delete_submission(database: Database, submission_id: str) -> None:
    # The API id is the externalid, or the submitid if there is none
    with database as db, db.transaction_cursor() as cursor:
        cursor.execute(
            "DELETE FROM submission WHERE externalid = %s OR submitid = %s",
            (submission_id, submission_id),
        )


def test_removed_team_member_is_detached(
    pyjudge_config: PyjudgeConfig, database: Database, base_url: str, uploaded: Contest
):
    description = users_description(pyjudge_config)
    teams = [
        team.model_copy(update={"members": ()}) if team.key == "user_team" else team
        for team in description.teams
    ]
    try:
        upload.upload_users(
            pyjudge_config, description.model_copy(update={"teams": teams})
        )
        assert _user_team(database) is None
        assert _scalar(
            database, "SELECT COUNT(*) FROM team WHERE externalid = 'user_team'"
        )
        with client(base_url, auth=ADMIN) as api:
            response = api.get("/api/v4/users/user")
            assert response.status_code == 200
            assert response.json()["team_id"] is None
    finally:
        upload.upload_users(pyjudge_config, description)
    assert _user_team(database) == "user_team"


def test_removing_contest_problems(
    pyjudge_config: PyjudgeConfig, database: Database, base_url: str, uploaded: Contest
):
    def upload_with(problems) -> None:
        upload.upload_contest(
            pyjudge_config,
            uploaded.model_copy(update={"problems": problems}),
            force=True,
            verify_problems=False,
        )

    all_problems = list(uploaded.problems)
    assert _contest_problems(database, uploaded) == {
        problem.problem_key for problem in all_problems
    }
    submission_id = _submit(
        base_url, "helloworld", {"main.py": b"print('team submission')\n"}
    )
    try:
        # Jury solutions only (system teams): the problem goes, with them
        upload_with([p for p in all_problems if p.problem_key != "dfamin"])
        assert "dfamin" not in _contest_problems(database, uploaded)

        # A team submitted: the upload refuses and changes nothing
        with pytest.raises(ValueError, match="team submissions"):
            upload_with([p for p in all_problems if p.problem_key != "helloworld"])
        assert "helloworld" in _contest_problems(database, uploaded)
    finally:
        _delete_submission(database, submission_id)
        upload_with(all_problems)
    assert _contest_problems(database, uploaded) == {
        problem.problem_key for problem in all_problems
    }
    with client(base_url, auth=ADMIN) as api:
        assert api.get("/jury/problems").status_code == 200


def test_multi_file_submission_in_export(
    database: Database, base_url: str, uploaded: Contest
):
    files = {
        "main.py": b"from helper import greet\n\ngreet()\n",
        "helper.py": b"def greet():\n    print('hello')\n",
    }
    # The example allows one file per submission (sourcefiles_limit), so the
    # second one goes in directly, as DOMjudge would store it
    submission_id = _submit(base_url, "helloworld", {"main.py": files["main.py"]})
    with database as db, db.transaction_cursor() as cursor:
        cursor.execute(
            "INSERT INTO submission_file (submitid, filename, ranknumber, sourcecode) "
            "SELECT submitid, 'helper.py', 2, %s FROM submission "
            "WHERE externalid = %s OR submitid = %s",
            (files["helper.py"], submission_id, submission_id),
        )
        assert cursor.rowcount == 1
    try:
        export = fetch_contest(database, uploaded.short_name)
        exported = [
            submission
            for submission in export.submissions
            if submission.external_id == submission_id
            or {file.filename for file in submission.files} == set(files)
        ]
        assert len(exported) == 1, export.submissions
        assert {file.filename: file.content for file in exported[0].files} == files
    finally:
        _delete_submission(database, submission_id)


def test_submission_filters(database: Database, base_url: str, uploaded: Contest):
    marker = uuid.uuid4().hex.encode()
    submission_id = _submit(
        base_url, "helloworld", {"hello.py": b"print('Hello World!')  # " + marker}
    )
    try:
        with database as connection:

            def ours(**filters) -> list:
                return [
                    submission
                    for submission in find_submissions(
                        connection, uploaded.short_name, **filters
                    )
                    if any(marker in file.content for file in submission.files)
                ]

            (submission,) = ours()
            team, problem = submission.team_name, submission.contest_problem_key
            others = {
                p.short_name
                for p in find_contest_problems(connection, uploaded.short_name)
            } - {problem}
            assert others
            assert ours(teams=[team], users=["user"], problems=[problem]) == [
                submission
            ]
            assert ours(teams=[]) == ours(users=["admin"]) == []
            assert ours(problems=others) == []
            with pytest.raises(TypeError, match="not a string"):
                find_submissions(connection, uploaded.short_name, teams=team)
    finally:
        _delete_submission(database, submission_id)
