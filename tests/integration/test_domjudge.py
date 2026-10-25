"""Upload the example setup into a real DOMjudge and check that DOMjudge can use it.

DOMjudge reads most of its data only when rendering pages, and answers with an
error page on data it does not expect, so the tests request the jury, team and
public pages and the API. The tests in this module run in order and share the
uploaded data.
"""

import hashlib
import html
import json
import re
import time
from collections import Counter, defaultdict
from collections.abc import Iterable

import httpx
import pytest

from pydomjudge.database import ContestDataExport, Database
from pydomjudge.database._db import DatabaseTransactionCursor
from pydomjudge.model import Contest, SystemCategory, User
from pydomjudge.scripts import upload
from pydomjudge.scripts.export import fetch_contest
from pydomjudge.scripts.upload import PyjudgeConfig, UsersDescription

from .conftest import ADMIN, DRY_RUN_REPORT, EXAMPLES, JUDGE, client

# Tables that change by using DOMjudge, not by uploading
VOLATILE_TABLES = {"auditlog", "sessions", "judgehost", "doctrine_migration_versions"}


def _upload_all(config: PyjudgeConfig, contest: Contest) -> None:
    upload.update_settings(config)
    description = UsersDescription.model_validate_json(
        (EXAMPLES / "users.json").read_text(),
        context={
            "category_by_key": {
                category.key: category
                for category in config.judge.team_categories + [SystemCategory.Jury]
            }
        },
    )
    upload.upload_users(config, description, overwrite_passwords=True)
    # The contest is running, which the upload refuses without force
    upload.upload_contest(config, contest, force=True)


@pytest.fixture(scope="module")
def uploaded(pyjudge_config: PyjudgeConfig, contest: Contest) -> Contest:
    _upload_all(pyjudge_config, contest)
    return contest


def _ids(database: Database, query: str) -> list:
    with database as db, db.transaction_cursor(readonly=True) as cursor:
        cursor.execute(query)
        return [row[0] for row in cursor.fetchall()]


def _error_of(response: httpx.Response) -> str:
    """The message of a DOMjudge (Symfony) error page, if any."""
    text = response.text
    for pattern in (
        r'<h1[^>]*class="[^"]*exception-message[^"]*"[^>]*>(.*?)</h1>',
        r"<title>(.*?)</title>",
    ):
        if match := re.search(pattern, text, re.S):
            return html.unescape(re.sub(r"\s+", " ", match[1])).strip()[:300]
    return text[:300]


def _check_pages(client: httpx.Client, urls: Iterable[str]) -> list[str]:
    failures = []
    for url in urls:
        response = client.get(url)
        if response.status_code != 200 or "/login" in str(response.url):
            failures.append(f"{url}: {response.status_code} {_error_of(response)}")
    return failures


# Jury pages reachable by GET without side effects; the crawl follows only these
SAFE_JURY_LINK = re.compile(
    r"^/jury/(contests|problems|teams|users|languages|executables|submissions"
    r"|clarifications|judgehosts|categories|affiliations)(/[A-Za-z0-9_.-]+)?$"
)
UNSAFE_WORDS = re.compile(
    r"edit|delete|rejudge|add|new|lock|unlock|toggle|request|refresh|finalize"
    r"|freeze|remove|change|enable|disable|claim|unclaim|send"
)


def test_upload_created_contest(database: Database, uploaded: Contest):
    assert _ids(database, "SELECT shortname FROM contest") == [uploaded.short_name]
    problems = _ids(database, "SELECT externalid FROM problem ORDER BY externalid")
    assert problems == sorted(problem.problem_key for problem in uploaded.problems)
    assert _ids(database, "SELECT COUNT(*) FROM submission")[0] > 0


def test_jury_pages(admin: httpx.Client, database: Database, uploaded: Contest):
    urls = [
        "/jury",
        "/jury/contests",
        "/jury/problems",
        "/jury/teams",
        "/jury/users",
        "/jury/categories",
        "/jury/affiliations",
        "/jury/languages",
        "/jury/executables",
        "/jury/submissions",
        "/jury/clarifications",
        "/jury/judgehosts",
        "/jury/scoreboard",
        "/jury/judging-verifier",
        "/jury/config",
    ]
    for table, column, prefix in [
        ("contest", "cid", "contests"),
        ("problem", "probid", "problems"),
        ("team", "teamid", "teams"),
        ("user", "userid", "users"),
        ("team_category", "categoryid", "categories"),
        ("team_affiliation", "affilid", "affiliations"),
        ("language", "langid", "languages"),
        ("executable", "execid", "executables"),
        ("submission", "submitid", "submissions"),
    ]:
        ids = _ids(database, f"SELECT {column} FROM `{table}` ORDER BY {column}")
        urls += [f"/jury/{prefix}/{entity_id}" for entity_id in ids]
    for problem_id in _ids(database, "SELECT probid FROM problem"):
        urls += [
            f"/jury/problems/{problem_id}/statement",
            f"/jury/problems/{problem_id}/testcases",
        ]

    failures = _check_pages(admin, urls)

    # Follow the safe links of the list pages, to catch pages not listed above
    seen = set(urls)
    crawled = []
    for page in urls[:16]:
        for link in re.findall(r'href="([^"#?]+)"', admin.get(page).text):
            if link not in seen and SAFE_JURY_LINK.match(link):
                if not UNSAFE_WORDS.search(link.split("/jury/", 1)[1]):
                    seen.add(link)
                    crawled.append(link)
    failures += _check_pages(admin, crawled)

    assert not failures, "\n".join(failures)


# Results of DOMjudge's own configuration check that are about the test setup,
# not about the uploaded data
EXPECTED_CHECK_FINDINGS = {
    "Non-default admin password",  # the example users.json sets admin/admin
    "User password hashing",  # bcrypt cost of the example hashes
}


def test_domjudge_config_check(admin: httpx.Client, uploaded: Contest):
    """DOMjudge's /jury/config/check validates contests, problems, languages and
    teams; every check must pass (E: error, W: warning)."""
    page = admin.get("/jury/config/check")
    assert page.status_code == 200
    results = re.findall(
        r'<h6 class="card-header result (\w)".*?float-end"></i>\s*(.*?)\s*</a>'
        r'.*?<div class="card-body">(.*?)</div>',
        page.text,
        re.S,
    )
    assert len(results) > 20, "config check page not understood"
    findings = [
        f"{status} {title}: "
        + re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
        for status, title, body in results
        if status in "EW" and title not in EXPECTED_CHECK_FINDINGS
    ]
    assert not findings, "\n".join(findings)


def test_team_and_public_pages(
    team: httpx.Client, base_url: str, database: Database, uploaded: Contest
):
    team_id = _ids(database, "SELECT teamid FROM team WHERE externalid = 'user_team'")[
        0
    ]
    problem_ids = _ids(database, "SELECT probid FROM problem ORDER BY probid")
    urls = [
        "/team",
        "/team/problems",
        "/team/scoreboard",
        "/team/docs",
        f"/team/team/{team_id}",
    ]
    for problem_id in problem_ids:
        urls += [
            f"/team/problems/{problem_id}/statement",
            f"/team/{problem_id}/samples.zip",
        ]
    failures = _check_pages(team, urls)
    # The example contest is not public, so the public pages show no problems
    with client(base_url) as public:
        failures += _check_pages(public, ["/public", "/public/problems"])
    assert not failures, "\n".join(failures)


def test_api(base_url: str, uploaded: Contest):
    with client(base_url, auth=ADMIN) as api:
        contests = api.get("/api/v4/contests").json()
        assert [contest["shortname"] for contest in contests] == [uploaded.short_name]
        contest_id = contests[0]["id"]
        failures = []
        for endpoint in [
            "problems",
            "teams",
            "organizations",
            "groups",
            "languages",
            "submissions",
            "judgements",
            "scoreboard",
            "state",
        ]:
            url = f"/api/v4/contests/{contest_id}/{endpoint}"
            response = api.get(url)
            if response.status_code != 200:
                failures.append(f"{url}: {response.status_code} {response.text[:300]}")
        assert not failures, "\n".join(failures)


def _dump(database: Database) -> dict[str, list[tuple]]:
    """All rows of all tables, in primary key order; blobs replaced by a hash."""
    with database as db, db.transaction_cursor(readonly=True) as cursor:
        cursor.execute("SHOW TABLES")
        tables = [table for (table,) in cursor.fetchall()]
        dump = {}
        for table in tables:
            cursor.execute(f"SELECT * FROM `{table}` ORDER BY 1")
            dump[table] = [
                tuple(
                    hashlib.md5(value).hexdigest()
                    if isinstance(value, bytes)
                    else value
                    for value in row
                )
                for row in cursor.fetchall()
            ]
    return dump


class _CountingCursor:
    """Passes everything to the real cursor and counts statements per table."""

    TABLE = re.compile(
        r"\b(?:INSERT\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM|FROM)\s+`?(\w+)`?",
        re.I,
    )

    def __init__(self, cursor, stats):
        self._cursor = cursor
        self._stats = stats

    def execute(self, query, params=None):
        result = self._cursor.execute(query, params)
        verb = query.split(None, 1)[0].upper()
        if verb != "SELECT":
            match = self.TABLE.search(query)
            table = match[1] if match else "?"
            self._stats[(verb, table)]["executed"] += 1
            self._stats[(verb, table)]["changed"] += max(self._cursor.rowcount, 0)
        return result

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __iter__(self):
        return iter(self._cursor)


def test_second_upload_changes_nothing(
    pyjudge_config: PyjudgeConfig,
    database: Database,
    uploaded: Contest,
    monkeypatch,
    request,
):
    before = _dump(database)
    stats: dict[tuple[str, str], Counter] = defaultdict(Counter)
    enter = DatabaseTransactionCursor.__enter__

    def counting_enter(self):
        return _CountingCursor(enter(self), stats)

    monkeypatch.setattr(DatabaseTransactionCursor, "__enter__", counting_enter)
    _upload_all(pyjudge_config, uploaded)
    monkeypatch.undo()
    after = _dump(database)

    report = [f"{'statement':30s} {'executed':>9s} {'changed':>9s}"]
    for (verb, table), counts in sorted(stats.items()):
        report.append(
            f"{verb + ' ' + table:30s} {counts['executed']:9d} {counts['changed']:9d}"
        )
    executed = sum(counts["executed"] for counts in stats.values())
    changed = sum(counts["changed"] for counts in stats.values())
    report.append(f"{'total':30s} {executed:9d} {changed:9d}")
    request.config.stash[DRY_RUN_REPORT] = report

    differences = []
    for table in sorted(set(before) | set(after)):
        if table in VOLATILE_TABLES:
            continue
        old, new = before.get(table, []), after.get(table, [])
        if old != new:
            removed = [row for row in old if row not in new]
            added = [row for row in new if row not in old]
            differences.append(
                f"{table}: {len(old)} -> {len(new)} rows, "
                f"removed {removed[:3]}, added {added[:3]}"
            )
    assert not differences, "\n".join(differences)


def test_export(database: Database, uploaded: Contest):
    export = fetch_contest(database, uploaded.short_name)
    assert ContestDataExport.model_validate_json(export.model_dump_json()) == export
    system_names = {category.name for category in SystemCategory.values()}
    assert all(team.category_name not in system_names for team in export.teams.values())
    assert set(export.problems) == {problem.name for problem in uploaded.problems}
    # Jury solutions are the only submissions, and they belong to system teams
    assert export.submissions == []
    assert "user_team" in export.teams


def test_readonly_cursor_rejects_writes(database: Database):
    import pymysql

    with pytest.raises(pymysql.err.MySQLError):
        with database as db, db.transaction_cursor(readonly=True) as cursor:
            cursor.execute("UPDATE contest SET name = name")


def test_update_password(database: Database, base_url: str, uploaded: Contest):
    from pydomjudge.database import update_user_password

    from .conftest import login

    with database as db, db.transaction_cursor() as cursor:
        update_user_password(cursor, "user", User.hash_password("changed"))
    try:
        login(base_url, "user", "changed").close()
    finally:
        with database as db, db.transaction_cursor() as cursor:
            update_user_password(cursor, "user", User.hash_password("user"))


@pytest.mark.skipif(not JUDGE, reason="needs the judgehost (run.sh with judge)")
def test_jury_solutions_judged_as_expected(
    admin: httpx.Client, database: Database, uploaded: Contest
):
    deadline = time.monotonic() + 120
    while not _ids(
        database, "SELECT COUNT(*) FROM judgehost WHERE polltime IS NOT NULL"
    )[0]:
        assert time.monotonic() < deadline, (
            "the judgehost did not connect, see "
            "docker compose -f tests/integration/compose.yml logs judgehost"
        )
        time.sleep(3)

    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        pending = _ids(
            database,
            "SELECT COUNT(*) FROM submission s "
            "LEFT JOIN judging j ON j.submitid = s.submitid AND j.valid = 1 "
            "WHERE j.result IS NULL",
        )[0]
        if not pending:
            break
        time.sleep(5)
    assert not pending, f"{pending} submissions not judged in time"

    results = _ids(
        database,
        "SELECT CONCAT(s.submitid, ' ', s.expected_results, ' ', j.result) "
        "FROM submission s JOIN judging j ON j.submitid = s.submitid AND j.valid = 1",
    )
    unexpected = [
        line
        for line in results
        if (parts := line.split(" ", 1))
        and parts[1].rsplit(" ", 1)[1].upper()
        not in json.loads(parts[1].rsplit(" ", 1)[0])
    ]
    assert not unexpected, "\n".join(unexpected)

    failures = _check_pages(admin, ["/jury/judging-verifier", "/jury/scoreboard"])
    failures += _check_pages(
        admin,
        [
            f"/jury/submissions/{submission_id}"
            for submission_id in _ids(database, "SELECT submitid FROM submission")
        ],
    )
    assert not failures, "\n".join(failures)


def test_consistency_report_of_the_example(database: Database, uploaded: Contest):
    from pydomjudge.database import check_consistency

    assert check_consistency(database) == []


def test_consistency_report_finds_broken_rows(database: Database, uploaded: Contest):
    from pydomjudge.database import ERROR, WARNING, Finding, check_consistency

    with database as db, db.transaction_cursor() as cursor:
        cursor.execute(
            "INSERT INTO team (name, display_name, categoryid, externalid) "
            "SELECT 'lonely', 'Lonely', categoryid, 'lonely' FROM team_category "
            "WHERE externalid = 'participants'"
        )
        cursor.execute(
            "INSERT INTO `user` (username, name, externalid, enabled) "
            "VALUES ('teamless', 'Teamless', 'teamless', 1)"
        )
        user_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO userrole (userid, roleid) "
            "SELECT %s, roleid FROM role WHERE role = 'team'",
            (user_id,),
        )
    try:
        findings = check_consistency(database)
        assert (
            Finding(
                ERROR,
                "user-without-team",
                "User teamless has the team role but no team, so cannot submit",
            )
            in findings
        )
        assert (
            Finding(WARNING, "team-without-users", "Team lonely has no users")
            in findings
        )
        assert findings[0].severity == ERROR  # errors first
    finally:
        with database as db, db.transaction_cursor() as cursor:
            cursor.execute("DELETE FROM `user` WHERE externalid = 'teamless'")
            cursor.execute("DELETE FROM team WHERE externalid = 'lonely'")
    assert check_consistency(database) == []
