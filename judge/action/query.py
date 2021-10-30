import datetime
from typing import List, Collection, Optional, Tuple, Dict, Generator

from mysql.connector.cursor import MySQLCursor

from judge.action.update import category_to_database
from judge.data.submission import SubmissionFileDto, SubmissionWithFilesDto, SubmissionWithVerdictDto, ClarificationDto, \
    ContestProblemDto
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
    return contest_id, contest_end


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
            f"  s.submitid, p.probid, j.result, s.submittime, s.langid, "
            f"  t.name, SUM(LENGTH(sf.sourcecode)), MAX(jr.runtime) "
            f"FROM team t "
            f"  JOIN submission s on t.teamid = s.teamid "
            f"  JOIN judging j ON j.submitid = s.submitid "
            f"  JOIN judging_run jr on j.judgingid = jr.judgingid "
            f"  JOIN submission_file sf on s.submitid = sf.submitid "
            f"  JOIN problem p on s.probid = p.probid "
            f"WHERE "
            f"  j.valid = 1 AND "
            f"  s.cid = ? AND "
            f"  p.probid IN {list_param(contest_problems_by_id)} "
            f"GROUP BY s.submitid ",
            (contest_id, *contest_problems_by_id.keys())
        )

        submission_ids = set()
        submissions = []
        for submission_id, problem_id, result, submission_time, language_key, team_key, size, runtime in cursor:
            if submission_id in submission_ids:
                raise ValueError(f"Submission {submission_id} has multiple valid judgings?")
            submission_ids.add(submission_id)
            submission = SubmissionWithVerdictDto(
                team_key=team_key,
                contest_key=contest_key,
                contest_problem_key=contest_problems_by_id[problem_id].contest_problem_key,
                language_key=language_key,
                verdict=parse_judging_verdict(result),
                submission_time=float(submission_time),
                size=int(size),
                too_late=contest_end < submission_time,
                runtime=float(runtime)
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
            f"SELECT c.clarid, p.probid, t.name, (c.recipient = t.teamid) as from_jury, c.body, c.respid, c.submittime "
            f"FROM problem p, clarification c, team t "
            f"WHERE "
            f"  c.probid = p.probid AND "
            f"  (t.teamid = c.sender OR t.teamid = c.recipient) AND "
            f"  p.probid IN {list_param(contest_problems_by_id)} ",
            tuple(contest_problems_by_id.keys())
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
                    raise ValueError(f"Inconsistent clarification {clarification_id} (missing response)")
                response_problem_id, response_team_key, response_from_jury, _, _, _ = clarification_data[response_id]
                if (problem_id, team_key, not from_jury) != \
                        (response_problem_id, response_team_key, response_from_jury):
                    raise ValueError(f"Inconsistent clarification {clarification_id} (invalid response)")
            clarification = ClarificationDto(
                team_key=team_key,
                request_time=submit_time,
                response=response_id,  # Hack
                from_jury=from_jury,
                contest_key=contest_key,
                contest_problem_key=contest_problems_by_id[problem_id].contest_problem_key,
                body=body
            )
            clarifications_by_id[clarification_id] = clarification
        for clarification in clarifications_by_id.values():
            if clarification.response is not None:
                clarification.response = clarifications_by_id[clarification.response]

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
