"""Contests and their problems, teams and categories.

Part of the writer, which works by key; see the package docstring.
"""

import datetime
import logging
import time

from pydomjudge.model import (
    Contest,
    SystemCategory,
)

from ._db import DBCursor as Cursor, field_not_in_list, get_scalar, list_param

log = logging.getLogger(__name__)


def _remove_dropped_contest_problems(
    cursor: Cursor, contest_id: int, problem_ids: list[int]
):
    """Remove contest problems that are no longer part of the contest.

    DOMjudge deletes the submissions of a removed contest problem (foreign key
    with ON DELETE CASCADE), so this refuses to remove problems with submissions
    by teams outside the system categories (jury solutions are regenerated).
    """
    system_keys = [category.key for category in SystemCategory.values()]
    cursor.execute(
        "SELECT cp.probid, cp.shortname, COUNT(s.submitid) "
        "FROM contestproblem cp "
        "  LEFT JOIN submission s ON s.cid = cp.cid AND s.probid = cp.probid "
        "    AND s.teamid NOT IN ("
        "      SELECT t.teamid FROM team t "
        "        JOIN team_category tc ON t.categoryid = tc.categoryid "
        f"      WHERE tc.externalid IN {list_param(system_keys)}) "
        f"WHERE cp.cid = %s AND {field_not_in_list('cp.probid', problem_ids)} "
        "GROUP BY cp.probid, cp.shortname",
        (*system_keys, contest_id, *problem_ids),
    )
    dropped = cursor.fetchall()
    with_submissions = [name for _, name, count in dropped if count]
    if with_submissions:
        raise ValueError(
            f"Problems {', '.join(with_submissions)} were removed from the contest "
            "but have team submissions, which DOMjudge would delete with them. "
            "Remove them in DOMjudge if this is intended."
        )
    if dropped:
        dropped_ids = [problem_id for problem_id, _, _ in dropped]
        log.info(
            "Removing problems %s from the contest",
            ", ".join(name for _, name, _ in dropped),
        )
        cursor.execute(
            "DELETE FROM contestproblem "
            f"WHERE cid = %s AND probid IN {list_param(dropped_ids)}",
            (contest_id, *dropped_ids),
        )


def create_or_update_contest_problems(
    cursor: Cursor,
    contest: Contest,
    contest_id: int,
    problem_ids: dict[str, int],
):
    _remove_dropped_contest_problems(
        cursor,
        contest_id,
        [problem_ids[problem.problem_key] for problem in contest.problems],
    )
    for contest_problem in contest.problems:
        # Cannot REPLACE INTO because of database triggers
        problem_id = problem_ids[contest_problem.problem_key]
        cursor.execute(
            "SELECT EXISTS(SELECT * FROM contestproblem WHERE cid = %s AND probid = %s)",
            (contest_id, problem_id),
        )
        if get_scalar(cursor):
            # Setting lazy_eval_results to EVAL_DEFAULT, which is 0, see domjudge/webapp/src/Service/DOMJudgeService.php
            cursor.execute(
                "UPDATE contestproblem SET "
                "shortname = %s, points = %s, allow_submit = TRUE, allow_judge = TRUE,"
                "color = %s, lazy_eval_results = 0 "
                "WHERE cid = %s AND probid = %s",
                (
                    contest_problem.name,
                    contest_problem.points,
                    contest_problem.color,
                    contest_id,
                    problem_id,
                ),
            )
        else:
            cursor.execute(
                "INSERT INTO contestproblem (cid, probid, shortname, points, allow_submit, "
                "allow_judge, color, lazy_eval_results) VALUES (%s, %s, %s, %s, TRUE, TRUE, %s, 0)",
                (
                    contest_id,
                    problem_id,
                    contest_problem.name,
                    contest_problem.points,
                    contest_problem.color,
                ),
            )


def create_or_update_contest(cursor: Cursor, contest: Contest, force=False) -> int:
    date_format = "%Y-%m-%d %H:%M:%S"

    def format_datetime(dt: datetime.datetime | None):
        if dt is None:
            return None
        # noinspection PyStringConversionWithoutDunderMethod
        return f"{dt.strftime(date_format)} {dt.tzinfo}"

    cursor.execute(
        "SELECT cid, starttime, endtime FROM contest WHERE externalid = %s",
        (contest.key,),
    )
    id_query = cursor.fetchone()
    if id_query:
        contest_id, current_start, current_end = id_query

        if float(current_start) <= time.time() <= float(current_end):
            if force:
                log.warning("Modified contest is currently running")
            else:
                raise ValueError("Modified contest is currently running")

        cursor.execute(
            "UPDATE contest SET "
            "externalid = %s, name = %s, shortname = %s, "
            "activatetime = %s, activatetime_string = %s, "
            "deactivatetime = %s, deactivatetime_string = %s, "
            "starttime = %s, starttime_string = %s, "
            "endtime = %s, endtime_string = %s, "
            "freezetime = %s, freezetime_string = %s, "
            "b = 0, enabled = TRUE, starttime_enabled = TRUE, process_balloons = FALSE, "
            "public = %s, open_to_all_teams = %s, warning_message = %s "
            "WHERE cid = %s",
            (
                contest.key,
                contest.name,
                contest.short_name,
                str(contest.activation_time.timestamp()),
                format_datetime(contest.activation_time),
                str(contest.deactivation_time.timestamp())
                if contest.deactivation_time
                else None,
                format_datetime(contest.deactivation_time),
                str(contest.start_time.timestamp()),
                format_datetime(contest.start_time),
                str(contest.end_time.timestamp()),
                format_datetime(contest.end_time),
                str(contest.freeze_time.timestamp()) if contest.freeze_time else None,
                format_datetime(contest.freeze_time),
                contest.public_scoreboard,
                contest.access is None,
                contest.warning_message,
                contest_id,
            ),
        )
    else:
        cursor.execute(
            "INSERT INTO contest (externalid, name, shortname, "
            "activatetime, activatetime_string, "
            "deactivatetime, deactivatetime_string, "
            "starttime, starttime_string, "
            "endtime, endtime_string, "
            "freezetime, freezetime_string, "
            "b, enabled, starttime_enabled, process_balloons, public, open_to_all_teams, warning_message) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, TRUE, TRUE, FALSE, %s, %s, %s)",
            (
                contest.key,
                contest.name,
                contest.short_name,
                str(contest.activation_time.timestamp()),
                format_datetime(contest.activation_time),
                str(contest.deactivation_time.timestamp())
                if contest.deactivation_time
                else None,
                format_datetime(contest.deactivation_time),
                str(contest.start_time.timestamp()),
                format_datetime(contest.start_time),
                str(contest.end_time.timestamp()),
                format_datetime(contest.end_time),
                str(contest.freeze_time.timestamp()) if contest.freeze_time else None,
                format_datetime(contest.freeze_time),
                contest.public_scoreboard,
                contest.access is None,
                contest.warning_message,
            ),
        )
        contest_id = cursor.lastrowid

    cursor.execute("DELETE FROM contestteam WHERE cid = %s", (contest_id,))
    cursor.execute("DELETE FROM contestteamcategory WHERE cid = %s", (contest_id,))

    if contest.access is not None:
        team_keys = contest.access.team_keys
        if team_keys:
            # noinspection SqlType
            cursor.execute(
                f"SELECT teamid FROM team WHERE externalid IN {list_param(team_keys)}",
                tuple(team_keys),
            )
            team_ids = cursor.fetchall()
            if len(team_ids) != len(team_keys):
                raise ValueError("Non-existing teams specified")
            for (team_id,) in team_ids:
                cursor.execute(
                    "INSERT INTO contestteam (cid, teamid) VALUES (%s, %s)",
                    (contest_id, team_id),
                )
        category_keys = contest.access.category_keys
        if category_keys:
            # noinspection SqlType
            cursor.execute(
                f"SELECT categoryid FROM team_category WHERE externalid IN {list_param(category_keys)}",
                tuple(category_keys),
            )
            category_ids = cursor.fetchall()
            if len(category_ids) != len(category_keys):
                raise ValueError("Non-existing team categories specified")
            for (category_id,) in category_ids:
                cursor.execute(
                    "INSERT INTO contestteamcategory (cid, categoryid) VALUES (%s, %s)",
                    (contest_id, category_id),
                )

    assert contest_id is not None
    return contest_id
