import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Collection

from pydomjudge.model import TeamCategory, SubmissionVerdict, TestcaseVerdict
from ._data import (
    SubmissionFileDto,
    ClarificationDto,
    ContestDescriptionDto,
    TestcaseResultDto,
    SubmissionDto,
    UserDto,
    TeamDto,
    ContestProblemDto,
)
from ._db import (
    Database,
    DBCursor as Cursor,
    list_param,
    field_in_list,
    field_not_in_list,
    get_unique_with_error,
)


def _find_contest_end(cursor: Cursor, contest_key: str) -> tuple[str, float]:
    cursor.execute(
        "SELECT cid, endtime FROM contest WHERE shortname = %s", (contest_key,)
    )
    contest_id, contest_end = get_unique_with_error(
        cursor, f"key {contest_key}", "contest"
    )
    return contest_id, float(contest_end)


def find_contest_problems(
    database: Database, contest_key: str
) -> list[ContestProblemDto]:
    with database.transaction_cursor(readonly=True) as cursor:
        cursor.execute("SELECT cid FROM contest WHERE shortname = %s", (contest_key,))

        (contest_id,) = get_unique_with_error(cursor, f"key {contest_key}", "contest")
        cursor.execute(
            "SELECT cp.shortname, cp.points, cp.color, p.name, p.externalid "
            "FROM contestproblem cp "
            "  JOIN problem p ON p.probid = cp.probid "
            "WHERE cid = %s",
            (contest_id,),
        )
        return [
            ContestProblemDto(
                short_name=short_name,
                points=points,
                color=color,
                problem_name=problem_name,
                problem_external_id=problem_external_id,
            )
            for (short_name, points, color, problem_name, problem_external_id) in cursor
        ]


def find_contest_keys(database: Database):
    with database.transaction_cursor(readonly=True) as cursor:
        cursor.execute("SELECT shortname FROM contest")
        return set(name for (name,) in cursor)


def find_contest_description(
    database: Database, contest_key: str
) -> ContestDescriptionDto:
    with database.transaction_cursor(readonly=True) as cursor:
        cursor.execute(
            "SELECT starttime, endtime FROM contest WHERE shortname = %s",
            (contest_key,),
        )
        start_time, end_time = get_unique_with_error(
            cursor, f"key {contest_key}", "contest"
        )
        return ContestDescriptionDto(
            contest_key=contest_key, start=float(start_time), end=float(end_time)
        )


def find_submissions(
    database: Database, contest_key: str, only_valid=True, include_files=True
) -> list[SubmissionDto]:
    with database.transaction_cursor(readonly=True) as cursor:
        contest_id, contest_end = _find_contest_end(cursor, contest_key)

        cursor.execute(
            "SELECT "
            "  s.submitid, cp.shortname, p.name, s.submittime, s.langid, s.externalid, t.name "
            "FROM submission s "
            "  JOIN team t on s.teamid = t.teamid "
            "  JOIN problem p on s.probid = p.probid "
            "  JOIN contestproblem cp on ( s.probid = cp.probid and s.cid = cp.cid ) "
            "WHERE "
            "  s.cid = %s",
            (contest_id,),
        )
        submission_data = {}
        for (
            submission_id,
            contest_problem_name,
            problem_name,
            submission_time,
            language_key,
            submission_external_id,
            team_name,
        ) in cursor:
            if submission_id in submission_data:
                logging.warning("Multiple results for submission %s", submission_id)
                continue
            submission_data[submission_id] = (
                float(submission_time),
                contest_problem_name,
                problem_name,
                language_key,
                team_name,
                submission_external_id,
            )

        if only_valid:
            cursor.execute(
                f"SELECT "
                f"  s.submitid, j.judgingid, j.result "
                f"FROM submission s "
                f"  JOIN judging j on s.submitid = j.submitid "
                f"WHERE "
                f"  j.valid = 1 AND "
                f"  s.submitid IN {list_param(submission_data)}",
                tuple(submission_data.keys()),
            )
        else:
            cursor.execute(
                f"SELECT "
                f"  s.submitid, j.judgingid, j.result "
                f"FROM submission s "
                f"  JOIN judging j on s.submitid = j.submitid "
                f"WHERE "
                f"  s.submitid IN {list_param(submission_data)}",
                tuple(submission_data.keys()),
            )
        judging_ids = set()
        judging_data: dict[int, tuple[int, SubmissionVerdict | None]] = {}
        for submission_id, judging_id, judging_result in cursor:
            if submission_id in judging_data:
                logging.warning("Multiple runs for submission %s", submission_id)
                continue
            if judging_id in judging_ids:
                logging.warning("Multiple judging ids for submission %s", submission_id)
                continue
            judging_ids.add(judging_id)
            judging_data[submission_id] = (
                judging_id,
                SubmissionVerdict.from_string(judging_result),
            )

        source_data: dict[str, dict[str, bytes]] = defaultdict(dict)
        if include_files:
            cursor.execute(
                f"SELECT "
                f"  s.submitid, sf.filename, sf.sourcecode "
                f"FROM submission s "
                f"  JOIN submission_file sf on s.submitid = sf.submitid "
                f"WHERE "
                f"  s.submitid IN {list_param(submission_data)} "
                f"GROUP BY s.submitid",
                tuple(submission_data.keys()),
            )
            for submission_id, filename, content in cursor:
                if isinstance(content, str):
                    content: bytes = content.encode("utf-8")
                elif isinstance(content, bytearray):
                    content = bytes(content)
                if not isinstance(content, bytes):
                    raise TypeError(type(content))
                source_data[submission_id][filename] = content

        cursor.execute(
            f"SELECT "
            f"  j.judgingid, jr.runtime, jr.testcaseid, jr.runresult "
            f"FROM judging j "
            f"  JOIN judging_run jr on j.judgingid = jr.judgingid "
            f"WHERE "
            f"  j.judgingid IN {list_param(judging_ids)}",
            tuple(judging_ids),
        )
        judging_testcases_db = defaultdict(list)
        testcase_ids = set()
        for judging_id, runtime, testcase_id, result in cursor:
            judging_testcases_db[judging_id].append(
                (
                    testcase_id,
                    round(float(runtime), 3),
                    TestcaseVerdict.from_string(result),
                )
            )
            testcase_ids.add(testcase_id)

        cursor.execute(
            f"SELECT "
            f"  t.testcaseid, t.orig_input_filename, t.sample "
            f"FROM testcase t "
            f"WHERE NOT t.deleted AND t.testcaseid IN {list_param(testcase_ids)}",
            tuple(testcase_ids),
        )
        testcases = {
            testcase_id: (name, bool(is_sample))
            for testcase_id, name, is_sample in cursor
        }

        judging_testcases = {}
        for judging_id, judging_cases in judging_testcases_db.items():
            cases = []
            for test_id, runtime, result in judging_cases:
                test_name, test_sample = testcases[test_id]
                cases.append(
                    TestcaseResultDto(
                        runtime=runtime,
                        verdict=result,
                        is_sample=test_sample,
                        test_name=test_name,
                    )
                )
            judging_testcases[judging_id] = cases

    submissions = []
    for submission_id, (
        submission_time,
        contest_problem_key,
        problem_name,
        language_key,
        team_name,
        submission_external_id,
    ) in submission_data.items():
        if submission_id not in judging_data:
            logging.warning(
                "No judging for submission %s by team %s", submission_id, team_name
            )
            continue
        judging_id, judging_result = judging_data[submission_id]
        testcases = judging_testcases.get(judging_id, [])
        if not testcases and (
            judging_result != SubmissionVerdict.COMPILER_ERROR
            and judging_result is not None
        ):
            logging.warning(
                "No testcases found for submission %s/judging %s with result %s",
                submission_id,
                judging_id,
                judging_result,
            )

        submissions.append(
            SubmissionDto(
                team_name=team_name,
                contest_key=contest_key,
                contest_problem_key=contest_problem_key,
                problem_name=problem_name,
                language_key=language_key,
                verdict=judging_result,
                submission_time=submission_time,
                too_late=contest_end < submission_time,
                case_result=testcases,
                files=[
                    SubmissionFileDto(filename=filename, content=content)
                    for (filename, content) in source_data[submission_id].items()
                ],
                external_id=submission_external_id,
            )
        )
    return submissions


def find_clarifications(
    database: Database, contest_key: str
) -> Collection[ClarificationDto]:
    with database.transaction_cursor(readonly=True) as cursor:
        cursor.execute(
            "SELECT c.clarid, c.probid, t.name, (c.recipient = t.teamid) as from_jury, c.body, c.respid, c.submittime, c.externalid "
            "FROM contest con, clarification c, team t "
            "WHERE "
            "  (t.teamid = c.sender OR t.teamid = c.recipient) AND "
            "  c.cid = con.cid AND "
            "  con.shortname = %s ",
            (contest_key,),
        )

        clarification_data = {
            clarification_id: (
                problem_id,
                team_key,
                bool(from_jury),
                body,
                response_id,
                float(submit_time),
                external_id,
            )
            for clarification_id, problem_id, team_key, from_jury, body, response_id, submit_time, external_id in cursor
        }
        problem_ids = {
            problem_id for problem_id, _, _, _, _, _, _ in clarification_data.values()
        }
        cursor.execute(
            "SELECT p.probid, p.name "
            "FROM problem p "
            "WHERE "
            f"  {field_in_list('p.probid', problem_ids)}",
            tuple(problem_ids),
        )
        problem_id_to_name = {
            problem_id: problem_name for problem_id, problem_name in cursor
        }

        clarifications_by_id = {}
        for clarification_id, (
            problem_id,
            team_name,
            from_jury,
            body,
            response_id,
            submit_time,
            external_id,
        ) in clarification_data.items():
            if response_id is not None:
                if response_id not in clarification_data:
                    raise ValueError(
                        f"Inconsistent clarification {clarification_id} (response not in list)"
                    )
                (
                    _,
                    response_team_name,
                    response_from_jury,
                    _,
                    _,
                    response_submit_time,
                    _,
                ) = clarification_data[response_id]
                if (team_name, not from_jury) != (
                    response_team_name,
                    response_from_jury,
                ):
                    raise ValueError(
                        f"Inconsistent clarification {clarification_id} (invalid response)"
                    )
                if submit_time < response_submit_time:
                    raise ValueError(
                        f"Response {clarification_id} to {response_id} sent before"
                    )
            clarifications_by_id[clarification_id] = ClarificationDto(
                identifier=str(
                    clarification_id
                ),  # This leaks the database id, but there is no other unique identifier, and we need one to model responses
                team_name=team_name,
                contest_key=contest_key,
                request_time=submit_time,
                response_to=str(response_id),
                from_jury=from_jury,
                contest_problem_key=problem_id_to_name[problem_id]
                if problem_id is not None
                else None,
                body=body,
                external_id=external_id,
            )

        return clarifications_by_id.values()


def find_users_by_login(database: Database, login_names: set[str]) -> list[UserDto]:
    if not login_names:
        return []
    with database.transaction_cursor(readonly=True) as cursor:
        # noinspection SqlType
        cursor.execute(
            f"SELECT u.name, u.username, u.email, u.teamid, u.externalid FROM user u "
            f"WHERE u.username IN {list_param(login_names)}",
            tuple(login_names),
        )
        return [
            UserDto(
                login_name=username,
                display_name=name,
                email=email,
                external_id=external_id,
            )
            for name, username, email, team_id, external_id in cursor
        ]


@dataclass(frozen=True)
class TeamData:
    db_id: int
    name: str
    display_name: str
    label: str
    external_id: str
    category_name: str
    affiliation_name: str


def _teams_from_data(cursor: Cursor, team_data: list[TeamData]) -> list[TeamDto]:
    team_by_id = {t.db_id: t for t in team_data}
    cursor.execute(
        f"SELECT u.teamid, u.username FROM user u "
        f"WHERE "
        f"  {field_in_list('u.teamid', team_by_id)}",
        tuple(team_by_id.keys()),
    )
    team_members = {team_id: [] for team_id in team_by_id.keys()}
    for team_id, name in cursor:
        team_members[team_id].append(name)
    return [
        TeamDto(
            name=team.name,
            display_name=team.display_name,
            category_name=team.category_name,
            affiliation_name=team.affiliation_name,
            label=team.label,
            external_id=team.external_id,
            member_login_names=team_members[team_id],
        )
        for team_id, team in team_by_id.items()
    ]


def find_teams_by_name(database: Database, names: set[str]) -> list[TeamDto]:
    if not names:
        return []
    with database.transaction_cursor(readonly=True) as cursor:
        cursor.execute(
            f"SELECT t.teamid, t.name, t.display_name, t.label, t.externalid, tc.name, ta.name FROM team t "
            f"  JOIN team_category tc on t.categoryid = tc.categoryid "
            f"  LEFT OUTER JOIN team_affiliation ta on t.affilid = ta.affilid "
            f"WHERE "
            f"  {field_in_list('t.name', names)}",
            tuple(names),
        )
        return _teams_from_data(
            cursor,
            [
                TeamData(
                    team_id,
                    name,
                    display_name,
                    label,
                    external_id,
                    category,
                    affiliation,
                )
                for team_id, name, display_name, label, external_id, category, affiliation in cursor
            ],
        )


def find_teams(
    database: Database, except_categories: list[str | TeamCategory] | None = None
) -> list[TeamDto]:
    with database.transaction_cursor(readonly=True) as cursor:
        if except_categories is None:
            except_categories = []
        except_category_names = [
            category.name if isinstance(category, TeamCategory) else str(category)
            for category in except_categories
        ]
        cursor.execute(
            f"SELECT t.teamid, t.name, t.display_name, t.label, t.externalid, tc.name, ta.name FROM team t "
            f"  JOIN team_category tc on t.categoryid = tc.categoryid "
            f"  LEFT OUTER JOIN team_affiliation ta on t.affilid = ta.affilid "
            f"WHERE "
            f"  {field_not_in_list('tc.name', except_category_names)} ",
            tuple(except_category_names),
        )
        return _teams_from_data(
            cursor,
            [
                TeamData(
                    team_id,
                    name,
                    display_name,
                    label,
                    external_id,
                    category,
                    affiliation,
                )
                for team_id, name, display_name, label, external_id, category, affiliation in cursor
            ],
        )


def find_languages(database: Database) -> dict[str, str]:
    with database.transaction_cursor(readonly=True) as cursor:
        cursor.execute("SELECT langid, name FROM language")
        return {language_key: name for language_key, name in cursor}
