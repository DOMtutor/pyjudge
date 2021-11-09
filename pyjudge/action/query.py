import logging
from typing import List, Collection, Optional, Tuple, Dict, Generator

from mysql.connector.cursor import MySQLCursor

from judge.action.update import category_to_database
from judge.data.submission import SubmissionFileDto, SubmissionWithFilesDto, SubmissionWithVerdictDto, \
    ClarificationDto, ContestProblemDto, SubmissionSize
from judge.data.teams import UserDto, TeamDto
from judge.db import Database, list_param, get_unique
from judge.model import Verdict, TeamCategory


def parse_judging_verdict(key):
    # noinspection SpellCheckingInspection
    return {
        "correct": Verdict.CORRECT,
        "wrong-answer": Verdict.WRONG_ANSWER,
        "timelimit": Verdict.TIME_LIMIT,
        "run-error": Verdict.RUN_ERROR,
        "memory-limit": Verdict.MEMORY_LIMIT,
        "output-limit": Verdict.OUTPUT_LIMIT,
        "no-output": Verdict.NO_OUTPUT,
        "compiler-error": Verdict.COMPILER_ERROR
    }[key]


def _find_contest_with_problems_by_key(cursor: MySQLCursor, contest_key: str) \
        -> Tuple[str, Dict[int, ContestProblemDto]]:
    cursor.execute("SELECT cid FROM contest WHERE shortname = ?", (contest_key,))
    contest_id = get_unique(cursor)[0]
    cursor.execute(
        "SELECT cp.shortname, cp.points, cp.probid, cp.color, p.externalid "
        "FROM contestproblem cp "
        "  JOIN problem p ON p.probid = cp.probid "
        "WHERE cid = ?",
        (contest_id,)
    )
    problems = {
        problem_id: ContestProblemDto(
            problem_key=problem_key,
            contest_problem_key=contest_name,
            points=points,
            color=color)
        for (contest_name, points, problem_id, color, problem_key) in cursor
    }
    return contest_id, problems


def _find_contest_end(cursor: MySQLCursor, contest_key: str) -> Tuple[str, float]:
    cursor.execute("SELECT cid, endtime FROM contest WHERE shortname = ?", (contest_key,))
    contest_id, contest_end = get_unique(cursor)
    return contest_id, float(contest_end)


def find_contest_problems(database: Database, contest_key: str) -> List[ContestProblemDto]:
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        _, problems = _find_contest_with_problems_by_key(cursor, contest_key)
        return list(problems.values())


def find_valid_submissions(database: Database, contest_key: str) -> List[SubmissionWithVerdictDto]:
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        contest_id, contest_problems_by_id = _find_contest_with_problems_by_key(cursor, contest_key)
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
            (contest_id, *contest_problems_by_id.keys())
        )
        submission_data = {}
        for submission_id, problem_id, submission_time, language_key, team_key in cursor:
            if submission_id in submission_data:
                logging.warning("Multiple results for submission %s", submission_id)
                continue
            contest_problem_key = contest_problems_by_id[problem_id].contest_problem_key
            submission_data[submission_id] = (float(submission_time), contest_problem_key, language_key, team_key)

        cursor.execute(
            f"SELECT "
            f"  s.submitid, j.judgingid, j.result "
            f"FROM submission s "
            f"  JOIN judging j on s.submitid = j.submitid "
            f"WHERE "
            f"  j.valid = 1 AND "
            f"  s.submitid IN {list_param(submission_data)}",
            tuple(submission_data.keys())
        )
        judging_ids = set()
        judging_data = {}
        for submission_id, judging_id, judging_result in cursor:
            if submission_id in judging_data:
                logging.warning("Multiple runs for submission %s", submission_id)
                continue
            if judging_id in judging_ids:
                logging.warning("Multiple judging ids for submission %s", submission_id)
                continue
            judging_ids.add(judging_id)
            judging_data[submission_id] = (judging_id, parse_judging_verdict(judging_result))

        cursor.execute(
            f"SELECT "
            f"  s.submitid, COUNT(sf.submitid), SUM(LENGTH(sf.sourcecode)), "
            f"  LENGTH(sourcecode) - LENGTH(REPLACE(sourcecode, '\n', '')) "
            f"FROM submission s "
            f"  JOIN submission_file sf on s.submitid = sf.submitid "
            f"WHERE "
            f"  s.submitid IN {list_param(submission_data)} "
            f"GROUP BY s.submitid",
            tuple(submission_data.keys())
        )
        source_data = {submission_id: (int(file_count), int(source_size), int(source_lines))
                       for submission_id, file_count, source_size, source_lines in cursor}

        cursor.execute(
            f"SELECT "
            f"  j.judgingid, MAX(jr.runtime) "
            f"FROM judging j "
            f"  JOIN judging_run jr on j.judgingid = jr.judgingid "
            f"WHERE "
            f"  j.judgingid IN {list_param(judging_ids)} "
            f"GROUP BY j.judgingid",
            tuple(judging_ids)
        )
        judging_runtime = {judging_id: float(runtime) for judging_id, runtime in cursor}

    submissions = []

    for submission_id, (submission_time, contest_problem_key, language_key, team_key) in submission_data.items():
        judging_id, judging_result = judging_data[submission_id]
        source_files, source_size, source_lines = source_data[submission_id]
        runtime = judging_runtime.get(judging_id, None)
        if runtime is None and judging_result != Verdict.COMPILER_ERROR:
            logging.warning("No runtime found for submission %s/judging %s with result %s",
                            submission_id, judging_id, judging_result)
        if runtime is not None:
            runtime = round(runtime, 3)  # Round to milliseconds

        submission = SubmissionWithVerdictDto(
            team_key=team_key,
            contest_key=contest_key,
            contest_problem_key=contest_problem_key,
            language_key=language_key,
            verdict=judging_result,
            submission_time=submission_time,
            size=SubmissionSize(file_count=source_files, line_count=source_lines, byte_size=source_size),
            too_late=contest_end < submission_time,
            maximum_runtime=runtime
        )
        submissions.append(submission)
    return submissions


def find_all_submissions_with_files(database: Database, contest_key: str) \
        -> Generator[SubmissionWithFilesDto, None, None]:
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        contest_id, contest_problems_by_id = _find_contest_with_problems_by_key(cursor, contest_key)

        cursor.execute(
            f"SELECT s.submitid, p.probid, p.externalid, s.submittime, s.langid, t.name "
            f"FROM team t "
            f"  JOIN submission s ON t.teamid = s.teamid "
            f"  JOIN problem p on s.probid = p.probid "
            f"WHERE "
            f"  p.probid IN {list_param(contest_problems_by_id)} ",
            tuple(contest_problems_by_id.keys())
        )
        submission_data = {
            submission_id: (contest_problems_by_id[problem_id], submission_time, language_key, team_name)
            for submission_id, problem_id, problem_name, submission_time, language_key, team_name in cursor
        }

        cursor.execute(
            f"SELECT s.submitid, sf.filename, sf.sourcecode "
            f"FROM submission s"
            f"  JOIN submission_file sf on s.submitid = sf.submitid "
            f"WHERE"
            f"  s.submitid IN {list_param(submission_data)} "
            f"ORDER BY"
            f"  s.submitid, sf.rank",
            tuple(submission_data.keys())
        )

        def make_submission(submission_id, submission_files):
            contest_problem, submission_time, language_key, team_key = submission_data[submission_id]
            return SubmissionWithFilesDto(
                team_key=team_key,
                contest_key=contest_key,
                contest_problem_key=contest_problem.contest_problem_key,
                language_key=language_key,
                submission_time=submission_time, files=list(submission_files)
            )

        current_id: Optional[int] = None
        current_files: List[SubmissionFileDto] = []
        for submission_id, filename, source_code in cursor:
            if current_id is None:
                current_id = submission_id
            if current_id != submission_id:
                yield make_submission(current_id, current_files)
                current_id, current_files = submission_id, []
            current_files.append(SubmissionFileDto(filename, source_code.decode("utf-8")))
        if current_id:
            yield make_submission(current_id, current_files)


def find_clarifications(database: Database, contest_key: str) -> Collection[ClarificationDto]:
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        contest_id, contest_problems_by_id = _find_contest_with_problems_by_key(cursor, contest_key)
        cursor.execute(
            f"SELECT c.clarid, c.probid, t.name, (c.recipient = t.teamid) as from_jury, c.body, c.respid, c.submittime "
            f"FROM problem p, clarification c, team t "
            f"WHERE "
            f"  (t.teamid = c.sender OR t.teamid = c.recipient) AND "
            f"  c.cid = ? ",
            (contest_id,)
        )

        clarification_data = {
            clarification_id: (problem_id, team_key, bool(from_jury), body, response_id, float(submit_time))
            for clarification_id, problem_id, team_key, from_jury, body, response_id, submit_time
            in cursor
        }
        clarifications_by_id = {}
        for clarification_id, (problem_id, team_key, from_jury, body, response_id, submit_time) in \
                clarification_data.items():
            if response_id is not None:
                if response_id not in clarification_data:
                    raise ValueError(f"Inconsistent clarification {clarification_id} (response not in list)")
                _, response_team_key, response_from_jury, _, _, _ = clarification_data[response_id]
                if (team_key, not from_jury) != (response_team_key, response_from_jury):
                    raise ValueError(f"Inconsistent clarification {clarification_id} (invalid response)")
            if problem_id is None:
                contest_problem_key = None
            else:
                contest_problem_key = contest_problems_by_id[problem_id].contest_problem_key

            clarification = ClarificationDto(
                key=str(clarification_id),
                team_key=team_key,
                request_time=submit_time,
                response_key=str(response_id),  # Hack
                from_jury=from_jury,
                contest_key=contest_key,
                contest_problem_key=contest_problem_key,
                body=body
            )
            clarifications_by_id[clarification_id] = clarification

        return clarifications_by_id.values()


def find_teams(database: Database, categories: List[TeamCategory]) -> List[TeamDto]:
    if not categories:
        return []
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        cursor.execute(
            f"SELECT t.teamid, t.name, t.display_name, tc.name FROM team t "
            f"  JOIN team_category tc on t.categoryid = tc.categoryid "
            f"WHERE "
            f"  tc.name IN {list_param(categories)} ",
            tuple(category_to_database[category] for category in categories)
        )
        team_data = {team_id: (key, name, category) for team_id, key, name, category in cursor}
        cursor.execute(
            f"SELECT u.name, u.username, u.email, u.teamid FROM user u "
            f"WHERE "
            f"  u.teamid IN {list_param(team_data)}",
            tuple(team_data.keys())
        )
        team_users = {team_id: [] for team_id in team_data.keys()}
        for name, username, email, team_id in cursor:
            team_users[team_id].append(UserDto(login_name=username, display_name=name, email=email))
        return [TeamDto(team_key, team_name, category, team_users[team_id])
                for team_id, (team_key, team_name, category) in team_data.items()]


def find_languages(database: Database) -> Dict[str, str]:
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        cursor.execute(f"SELECT langid, name FROM language")
        return {language_key: name for language_key, name in cursor}
