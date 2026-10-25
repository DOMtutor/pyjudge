"""Consistency report of a DOMjudge database (read only).

Complements DOMjudge's own configuration check (/jury/config/check), which
validates entities one by one (problems have test cases, languages a compile
script, ...): these checks look at how users, teams, categories, problems and
contests fit together, and at the verdicts of the jury solutions.
"""

import dataclasses
import json
import time

from pydomjudge.model import SystemCategory

from ._db import Database, DBCursor as Cursor, list_param

ERROR = "error"
WARNING = "warning"
INFO = "info"


@dataclasses.dataclass(frozen=True)
class Finding:
    severity: str  # error: DOMjudge cannot work like this; warning: likely wrong
    check: str
    message: str


def _rows(cursor: Cursor, query: str, params=()) -> list[tuple]:
    cursor.execute(query, params)
    return list(cursor.fetchall())


_SYSTEM_KEYS = tuple(category.key for category in SystemCategory.values())


def _not_system_category(alias: str) -> str:
    return (
        f"({alias}.externalid IS NULL OR "
        f"{alias}.externalid NOT IN {list_param(_SYSTEM_KEYS)})"
    )


def _teams_without_users(cursor: Cursor) -> list[Finding]:
    rows = _rows(
        cursor,
        "SELECT t.name FROM team t "
        "LEFT JOIN team_category c ON c.categoryid = t.categoryid "
        f"WHERE {_not_system_category('c')} AND NOT EXISTS "
        "(SELECT 1 FROM `user` u WHERE u.teamid = t.teamid) "
        "ORDER BY t.name",
        _SYSTEM_KEYS,
    )
    return [
        Finding(WARNING, "team-without-users", f"Team {name} has no users")
        for (name,) in rows
    ]


def _teams_without_category(cursor: Cursor) -> list[Finding]:
    rows = _rows(cursor, "SELECT name FROM team WHERE categoryid IS NULL ORDER BY name")
    return [
        Finding(
            WARNING,
            "team-without-category",
            f"Team {name} has no category (its category was deleted?)",
        )
        for (name,) in rows
    ]


def _team_users_without_team(cursor: Cursor) -> list[Finding]:
    rows = _rows(
        cursor,
        "SELECT u.username FROM `user` u "
        "JOIN userrole ur ON ur.userid = u.userid "
        "JOIN role r ON r.roleid = ur.roleid "
        "WHERE r.role = 'team' AND u.teamid IS NULL AND u.enabled = 1 "
        "ORDER BY u.username",
    )
    return [
        Finding(
            ERROR,
            "user-without-team",
            f"User {username} has the team role but no team, so cannot submit",
        )
        for (username,) in rows
    ]


def _unused_categories(cursor: Cursor) -> list[Finding]:
    rows = _rows(
        cursor,
        "SELECT c.name FROM team_category c "
        f"WHERE {_not_system_category('c')} AND NOT EXISTS "
        "(SELECT 1 FROM team t WHERE t.categoryid = c.categoryid) "
        "ORDER BY c.name",
        _SYSTEM_KEYS,
    )
    return [
        Finding(INFO, "unused-category", f"Category {name} has no teams")
        for (name,) in rows
    ]


def _problems_without_contest(cursor: Cursor) -> list[Finding]:
    rows = _rows(
        cursor,
        "SELECT p.name FROM problem p "
        "WHERE NOT EXISTS (SELECT 1 FROM contestproblem cp WHERE cp.probid = p.probid) "
        "ORDER BY p.name",
    )
    return [
        Finding(INFO, "problem-without-contest", f"Problem {name} is in no contest")
        for (name,) in rows
    ]


def _contest_problems_without_testcases(cursor: Cursor) -> list[Finding]:
    rows = _rows(
        cursor,
        "SELECT c.shortname, cp.shortname, p.name FROM contestproblem cp "
        "JOIN contest c ON c.cid = cp.cid "
        "JOIN problem p ON p.probid = cp.probid "
        "WHERE NOT EXISTS (SELECT 1 FROM testcase t "
        "  WHERE t.probid = cp.probid AND NOT t.deleted) "
        "ORDER BY c.shortname, cp.shortname",
    )
    return [
        Finding(
            ERROR,
            "problem-without-testcases",
            f"Problem {label} ({name}) of contest {contest} has no test cases",
        )
        for contest, label, name in rows
    ]


def _contests(cursor: Cursor, now: float) -> list[Finding]:
    findings = []
    rows = _rows(
        cursor,
        "SELECT c.shortname, c.open_to_all_teams, "
        "  (SELECT COUNT(*) FROM contestproblem cp WHERE cp.cid = c.cid), "
        "  (SELECT COUNT(*) FROM contestteam ct WHERE ct.cid = c.cid) + "
        "  (SELECT COUNT(*) FROM contestteamcategory cc WHERE cc.cid = c.cid) "
        "FROM contest c "
        "WHERE c.enabled = 1 AND c.activatetime <= %s "
        "  AND COALESCE(c.deactivatetime, c.endtime) >= %s "
        "ORDER BY c.shortname",
        (now, now),
    )
    for shortname, open_to_all, problems, audience in rows:
        if not problems:
            findings.append(
                Finding(
                    WARNING,
                    "contest-without-problems",
                    f"Active contest {shortname} has no problems",
                )
            )
        if not open_to_all and not audience:
            findings.append(
                Finding(
                    WARNING,
                    "contest-without-teams",
                    f"Active contest {shortname} is open to no team or category",
                )
            )
    return findings


def _languages_not_judged(cursor: Cursor) -> list[Finding]:
    rows = _rows(
        cursor,
        "SELECT l.langid, COUNT(*) FROM submission s "
        "JOIN language l ON l.langid = s.langid "
        "JOIN judging j ON j.submitid = s.submitid AND j.valid = 1 "
        "WHERE l.allow_judge = 0 AND s.valid = 1 AND j.result IS NULL "
        "GROUP BY l.langid "
        "ORDER BY l.langid",
    )
    return [
        Finding(
            WARNING,
            "language-not-judged",
            f"Language {language} is not judged, but {count} submissions wait for it",
        )
        for language, count in rows
    ]


def _unexpected_jury_results(cursor: Cursor) -> list[Finding]:
    rows = _rows(
        cursor,
        "SELECT s.submitid, t.name, p.name, f.filename, s.expected_results, j.result "
        "FROM submission s "
        "JOIN judging j ON j.submitid = s.submitid AND j.valid = 1 "
        "JOIN team t ON t.teamid = s.teamid "
        "JOIN problem p ON p.probid = s.probid "
        "LEFT JOIN submission_file f ON f.submitid = s.submitid AND f.ranknumber = 1 "
        "WHERE s.valid = 1 AND s.expected_results IS NOT NULL "
        "  AND j.result IS NOT NULL "
        "ORDER BY p.name, f.filename",
    )
    findings = []
    for submit_id, team, problem, file_name, expected, result in rows:
        try:
            expected_keys = json.loads(expected)
        except ValueError:
            expected_keys = []
        if result.upper() not in expected_keys:
            findings.append(
                Finding(
                    WARNING,
                    "unexpected-jury-result",
                    f"Jury solution {file_name or submit_id} of {problem} ({team}): "
                    f"{result}, expected {', '.join(expected_keys) or 'nothing'}",
                )
            )
    return findings


CHECKS = [
    _team_users_without_team,
    _contest_problems_without_testcases,
    _teams_without_users,
    _teams_without_category,
    _languages_not_judged,
    _unexpected_jury_results,
    _unused_categories,
    _problems_without_contest,
]


def check_consistency(database: Database, now: float | None = None) -> list[Finding]:
    """All findings, errors first."""
    findings: list[Finding] = []
    with database as db, db.transaction_cursor(readonly=True) as cursor:
        for check in CHECKS:
            findings += check(cursor)
        findings += _contests(cursor, time.time() if now is None else now)
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    return sorted(findings, key=lambda finding: order[finding.severity])
