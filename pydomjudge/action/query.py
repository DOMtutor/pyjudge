import logging
from collections import defaultdict
from typing import List, Collection, Tuple, Dict, Generator, Optional

from mysql.connector.cursor import MySQLCursor

from pydomjudge.data.submission import (
    SubmissionDto,
    SubmissionFileDto,
    ClarificationDto,
    ContestProblemDto,
    ContestDescriptionDto,
    TestcaseResultDto,
)
from pydomjudge.data.teams import UserDto, TeamDto
from pydomjudge.model import Verdict
from pydomjudge.model.submission import TestcaseVerdict
from pydomjudge.model.team import SystemCategory
from pydomjudge.scripts.db import Database, list_param, get_unique, field_in_list


def parse_judging_verdict(key):
    if key is None:
        return None
    # noinspection SpellCheckingInspection
    return {
        "correct": Verdict.CORRECT,
        "wrong-answer": Verdict.WRONG_ANSWER,
        "timelimit": Verdict.TIME_LIMIT,
        "run-error": Verdict.RUN_ERROR,
        "memory-limit": Verdict.MEMORY_LIMIT,
        "output-limit": Verdict.OUTPUT_LIMIT,
        "no-output": Verdict.NO_OUTPUT,
        "compiler-error": Verdict.COMPILER_ERROR,
    }[key]


def _find_contest_with_problems_by_key(
    cursor: MySQLCursor, contest_key: str
) -> Tuple[str, Dict[int, ContestProblemDto]]:
    cursor.execute("SELECT cid FROM contest WHERE shortname = ?", (contest_key,))
    contest_id = get_unique(cursor)[0]
    cursor.execute(
        "SELECT cp.shortname, cp.points, cp.probid, cp.color, p.externalid "
        "FROM contestproblem cp "
        "  JOIN problem p ON p.probid = cp.probid "
        "WHERE cid = ?",
        (contest_id,),
    )
    problems = {
        problem_id: ContestProblemDto(
            problem_key=problem_key,
            contest_problem_key=contest_name,
            points=points,
            color=color,
        )
        for (contest_name, points, problem_id, color, problem_key) in cursor
    }
    return contest_id, problems


def _find_contest_end(cursor: MySQLCursor, contest_key: str) -> Tuple[str, float]:
    cursor.execute(
        "SELECT cid, endtime FROM contest WHERE shortname = ?", (contest_key,)
    )
    contest_id, contest_end = get_unique(cursor)
    return contest_id, float(contest_end)


def find_contest_problems(
    database: Database, contest_key: str
) -> List[ContestProblemDto]:
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        _, problems = _find_contest_with_problems_by_key(cursor, contest_key)
        return list(problems.values())


def find_contest_description(
    database: Database, contest_key: str
) -> ContestDescriptionDto:
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        cursor.execute(
            "SELECT starttime, endtime FROM contest WHERE shortname = ?", (contest_key,)
        )
        start_time, end_time = get_unique(cursor)
        return ContestDescriptionDto(
            contest_key=contest_key, start=float(start_time), end=float(end_time)
        )


def find_submissions(
    database: Database, contest_key: str, only_valid=True
) -> Generator[SubmissionDto, None, None]:
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        contest_id, contest_problems_by_id = _find_contest_with_problems_by_key(
            cursor, contest_key
        )
        _, contest_end = _find_contest_end(cursor, contest_key)

        cursor.execute(
            f"SELECT "
            f"  s.submitid, p.probid, s.submittime, s.langid, t.name "
            f"FROM team t "
            f"  JOIN submission s on t.teamid = s.teamid "
            f"  JOIN problem p on s.probid = p.probid "
            f"WHERE "
            f"  s.cid = ? AND "
            f"  p.probid IN {list_param(contest_problems_by_id)} ",
            (contest_id, *contest_problems_by_id.keys()),
        )
        submission_data = {}
        for (
            submission_id,
            problem_id,
            submission_time,
            language_key,
            team_key,
        ) in cursor:
            if submission_id in submission_data:
                logging.warning("Multiple results for submission %s", submission_id)
                continue
            contest_problem = contest_problems_by_id[problem_id]
            submission_data[submission_id] = (
                float(submission_time),
                contest_problem.contest_problem_key,
                contest_problem.problem_key,
                language_key,
                team_key,
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
        judging_data: dict[int, tuple[int, Optional[Verdict]]] = {}
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
                parse_judging_verdict(judging_result),
            )

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
        source_data = defaultdict(dict)
        for submission_id, filename, content in cursor:
            if isinstance(content, str):
                content = content.encode("utf-8")
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
                (testcase_id, round(float(runtime), 3), TestcaseVerdict.parse(result))
            )
            testcase_ids.add(testcase_id)

        cursor.execute(
            f"SELECT "
            f"  t.testcaseid, t.orig_input_filename, t.sample "
            f"FROM testcase t "
            f"WHERE NOT t.deleted AND t.testcaseid IN {list_param(testcase_ids)}",
            tuple(testcase_ids),
        )
        testcases = {}
        for testcase_id, name, is_sample in cursor:
            testcases[testcase_id] = (name, bool(is_sample))

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

    for submission_id, (
        submission_time,
        contest_problem_key,
        problem_key,
        language_key,
        team_key,
    ) in submission_data.items():
        if submission_id not in judging_data:
            logging.warning(
                "No judging for submission %s by team %s", submission_id, team_key
            )
            continue
        judging_id, judging_result = judging_data[submission_id]
        testcases = judging_testcases.get(judging_id, [])
        if not testcases and (
            judging_result != Verdict.COMPILER_ERROR and judging_result is not None
        ):
            logging.warning(
                "No testcases found for submission %s/judging %s with result %s",
                submission_id,
                judging_id,
                judging_result,
            )

        yield SubmissionDto(
            team_key=team_key,
            contest_key=contest_key,
            contest_problem_key=contest_problem_key,
            problem_key=problem_key,
            language_key=language_key,
            verdict=judging_result,
            submission_time=submission_time,
            files=[
                SubmissionFileDto(filename, content)
                for (filename, content) in source_data[submission_id].items()
            ],
            too_late=contest_end < submission_time,
            case_result=testcases,
        )


def find_clarifications(
    database: Database, contest_key: str
) -> Collection[ClarificationDto]:
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        contest_id, contest_problems_by_id = _find_contest_with_problems_by_key(
            cursor, contest_key
        )
        cursor.execute(
            "SELECT c.clarid, c.probid, t.name, (c.recipient = t.teamid) as from_jury, c.body, c.respid, c.submittime "
            "FROM problem p, clarification c, team t "
            "WHERE "
            "  (t.teamid = c.sender OR t.teamid = c.recipient) AND "
            "  c.cid = ? ",
            (contest_id,),
        )

        clarification_data = {
            clarification_id: (
                problem_id,
                team_key,
                bool(from_jury),
                body,
                response_id,
                float(submit_time),
            )
            for clarification_id, problem_id, team_key, from_jury, body, response_id, submit_time in cursor
        }
        clarifications_by_id = {}
        for clarification_id, (
            problem_id,
            team_key,
            from_jury,
            body,
            response_id,
            submit_time,
        ) in clarification_data.items():
            if response_id is not None:
                if response_id not in clarification_data:
                    raise ValueError(
                        f"Inconsistent clarification {clarification_id} (response not in list)"
                    )
                (
                    _,
                    response_team_key,
                    response_from_jury,
                    _,
                    _,
                    response_submit_time,
                ) = clarification_data[response_id]
                if (team_key, not from_jury) != (response_team_key, response_from_jury):
                    raise ValueError(
                        f"Inconsistent clarification {clarification_id} (invalid response)"
                    )
                if submit_time < response_submit_time:
                    raise ValueError(
                        f"Response {clarification_id} to {response_id} sent before"
                    )
            if problem_id is None:
                contest_problem_key = None
            else:
                contest_problem_key = contest_problems_by_id[
                    problem_id
                ].contest_problem_key

            clarification = ClarificationDto(
                key=str(clarification_id),
                team_key=team_key,
                request_time=submit_time,
                response_to=str(response_id),  # Hack
                from_jury=from_jury,
                contest_key=contest_key,
                contest_problem_key=contest_problem_key,
                body=body,
            )
            clarifications_by_id[clarification_id] = clarification

        return clarifications_by_id.values()


def find_non_system_teams(database: Database) -> List[TeamDto]:
    system_categories = {category.database_name for category in SystemCategory}

    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        cursor.execute(
            f"SELECT t.teamid, t.name, t.display_name, tc.name FROM team t "
            f"  JOIN team_category tc on t.categoryid = tc.categoryid "
            f"WHERE "
            f"  tc.name NOT IN {list_param(system_categories)} ",
            tuple(system_categories),
        )
        team_data = {
            team_id: (key, name, category) for team_id, key, name, category in cursor
        }
        cursor.execute(
            f"SELECT u.name, u.username, u.email, u.teamid FROM user u "
            f"WHERE "
            f"  {field_in_list("u.teamid", team_data)}",
            tuple(team_data.keys()),
        )
        team_users = {team_id: [] for team_id in team_data.keys()}
        for name, username, email, team_id in cursor:
            team_users[team_id].append(
                UserDto(login_name=username, display_name=name, email=email)
            )
        return [
            TeamDto(team_key, team_name, category, team_users[team_id])
            for team_id, (team_key, team_name, category) in team_data.items()
        ]


def find_languages(database: Database) -> Dict[str, str]:
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        cursor.execute("SELECT langid, name FROM language")
        return {language_key: name for language_key, name in cursor}
