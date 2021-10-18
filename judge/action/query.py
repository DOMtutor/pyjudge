from typing import List, Collection, Optional

from mysql.connector.cursor import MySQLCursor

from judge.action.update import category_to_database
from judge.data.submission import SubmissionFileDto, SubmissionWithFilesDto, SubmissionWithVerdictDto, ClarificationDto
from judge.model import Contest, Verdict, TeamCategory
from judge.db import Database, list_param, get_unique
from judge.data.teams import UserDto, TeamDto


def parse_judging_verdict(key):
    return {
        "correct": Verdict.CORRECT,
        "wrong_answer": Verdict.WRONG_ANSWER,
        "time_limit": Verdict.TIME_LIMIT,
        "run_error": Verdict.RUN_ERROR,
        "memory_limit": Verdict.MEMORY_LIMIT,
        "output_limit": Verdict.OUTPUT_LIMIT,
        "no_output": Verdict.NO_OUTPUT
    }[key]


def _find_contest_with_problems(cursor: MySQLCursor, contest: Contest):
    cursor.execute("SELECT cid FROM contest WHERE externalid = ?", (contest.key,))
    contest_id = get_unique(cursor)[0]

    cursor.execute("SELECT shortname, points, probid FROM contestproblem "
                   "WHERE cid = ?", (contest_id,))
    problem_points = {name: (points, problem_id) for (name, points, problem_id) in cursor}

    if len(problem_points) != len(contest.problems):
        raise ValueError(f"Expected {len(contest.problems)} problems, but only found {len(problem_points)}")
    for contest_problem in contest.problems:
        if contest_problem.name not in problem_points:
            raise ValueError(f"Problem {contest_problem} is specified for contest {contest} but does not exist")
        problem_id, points = problem_points[contest_problem.name]
        if points != contest_problem.points:
            raise ValueError(f"Problem with id {problem_id} of contest {contest} should have "
                             f"{contest_problem.points} but has {points}")

    problem_name_by_id = {problem_id: name for name, (_, problem_id) in problem_points.items()}

    return contest_id, problem_name_by_id


def _find_contest_with_problems_by_key(cursor: MySQLCursor, contest_key: str):
    cursor.execute("SELECT cid FROM contest WHERE externalid = ?", (contest_key,))
    contest_id = get_unique(cursor)[0]
    cursor.execute("SELECT shortname, points, probid FROM contestproblem "
                   "WHERE cid = ?", (contest_id,))
    problem_points = {name: (points, problem_id) for (name, points, problem_id) in cursor}
    problem_name_by_id = {problem_id: name for name, (_, problem_id) in problem_points.items()}
    return contest_id, problem_name_by_id


def find_valid_submissions(database: Database,
                           contest_key: str) -> List[SubmissionWithVerdictDto]:
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        contest_id, problem_contest_name_by_id = _find_contest_with_problems_by_key(cursor, contest_key)
        cursor.execute(f"SELECT s.submitid, p.probid, j.result, s.submittime, s.langid, t.name, "
                       f"   SUM(LENGTH(sf.sourcecode)) as length "
                       f"FROM team t "
                       f"  JOIN submission s on t.teamid = s.teamid "
                       f"  JOIN judging j ON j.submitid = s.submitid "
                       f"  JOIN submission_file sf on s.submitid = sf.submitid "
                       f"  JOIN problem p on s.probid = p.probid "
                       f"WHERE "
                       f"  j.valid = 1 AND "
                       f"  s.cid = ? AND "
                       f"  p.probid IN {list_param(problem_contest_name_by_id)} "
                       f"GROUP BY s.submitid",
                       (contest_id, *problem_contest_name_by_id.keys()))

        submission_ids = set()
        submissions = []
        for submission_id, problem_id, result, submission_time, language_key, team_key, size in cursor:
            if submission_id in submission_ids:
                raise ValueError(f"Submission {submission_id} has multiple valid judgings?")
            submission_ids.add(submission_id)
            submission = SubmissionWithVerdictDto(team_key=team_key,
                                                  contest_key=contest_key,
                                                  contest_problem_key=problem_contest_name_by_id[problem_id],
                                                  language_key=language_key,
                                                  verdict=parse_judging_verdict(result),
                                                  submission_time=submission_time,
                                                  size=size)
            submissions.append(submission)
    return submissions


def find_all_submissions_with_files(database: Database,
                                    contest_key: str) -> List[SubmissionWithVerdictDto]:
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        contest_id, problem_contest_name_by_id = _find_contest_with_problems_by_key(cursor, contest_key)

        cursor.execute(f"SELECT s.submitid, p.probid, p.externalid, s.submittime, s.langid, t.name "
                       f"FROM team t "
                       f"  JOIN submission s ON t.teamid = s.teamid "
                       f"  JOIN problem p on s.probid = p.probid "
                       f"WHERE "
                       f"  p.probid IN {list_param(problem_contest_name_by_id)} ",
                       (*problem_contest_name_by_id.keys(), contest_id,))
        submission_data = {submission_id: (problem_contest_name_by_id[problem_id], submission_time, language_key,
                                           team_name)
                           for submission_id, problem_id, problem_name, submission_time, language_key, team_name
                           in cursor}

        cursor.execute(f"SELECT s.submitid, sf.filename, sf.sourcecode "
                       f"FROM submission s"
                       f"  JOIN submission_file sf on s.submitid = sf.submitid "
                       f"WHERE"
                       f"  s.submitid IN {list_param(submission_data)} "
                       f"ORDER BY"
                       f"  s.submitid, sf.rank",
                       tuple(submission_data.keys()))

        def make_submission(submission_id, submission_files):
            contest_problem_key, submission_time, language_key, team_key = submission_data[submission_id]
            return SubmissionWithFilesDto(team_key=team_key,
                                          contest_key=contest_key,
                                          contest_problem_key=contest_problem_key,
                                          language_key=language_key,
                                          submission_time=submission_time, files=list(submission_files))

        current_id: Optional[int] = None
        current_files: List[SubmissionFileDto] = []
        for submission_id, filename, source_code in cursor:
            if current_id is None:
                current_id = submission_id
            if current_id != submission_id:
                yield make_submission(current_id, current_files)
                current_id, current_files = submission_id, []
            current_files.append(SubmissionFileDto(filename, source_code))
        if current_id:
            yield make_submission(current_id, current_files)


def find_clarifications(database: Database,
                        contest_key: str) -> Collection[ClarificationDto]:
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        contest_id, problem_contest_name_by_id = _find_contest_with_problems_by_key(cursor, contest_key)
        cursor.execute(f"SELECT c.clarid, p.probid, t.name, (c.recipient = t.teamid) as from_jury, c.body, c.respid,"
                       f" c.submittime "
                       f"FROM problem p, clarification c, team t "
                       f"WHERE "
                       f"  c.probid = p.probid AND "
                       f"  (t.teamid = c.sender OR t.teamid = c.recipient) AND "
                       f"  p.probid IN {list_param(problem_contest_name_by_id)}  ",
                       tuple(problem_contest_name_by_id.keys()))

        clarification_data = {clarification_id: (problem_id, team_key, from_jury, body, response_id, submit_time)
                              for clarification_id, problem_id, team_key, from_jury, body, response_id, submit_time
                              in cursor}
        clarifications_by_id = {}
        for clarification_id, (problem_id, team_key, from_jury, body, response_id, submit_time) in \
                clarification_data.items():
            if response_id not in clarification_data:
                raise ValueError(f"Inconsistent clarification {clarification_id}")
            response_problem_id, response_team_name, response_from_jury, _, _, _ = clarification_data[response_id]
            if (problem_id, response_problem_id, not from_jury) != \
                    (response_problem_id, response_team_name, response_from_jury):
                raise ValueError(f"Inconsistent clarification {clarification_id}")
            clarification = ClarificationDto(team_key=team_key,
                                             request_time=submit_time,
                                             response=response_id,  # Hack
                                             from_jury=from_jury,
                                             contest_key=contest_key,
                                             contest_problem_key=problem_contest_name_by_id[problem_id],
                                             body=body)
            clarifications_by_id[clarification_id] = clarification
        for clarification in clarifications_by_id.values():
            if clarification.response is not None:
                clarification.response = clarifications_by_id[clarification.response]

        return clarifications_by_id.values()


def find_teams(database: Database, categories: List[TeamCategory]) -> List[TeamDto]:
    if not categories:
        return []
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        cursor.execute(f"SELECT t.teamid, t.name, t.display_name, tc.name FROM team t "
                       f"  JOIN team_category tc on t.categoryid = tc.categoryid "
                       f"WHERE "
                       f"  tc.name IN {list_param(categories)} ",
                       tuple(category_to_database[category] for category in categories))
        team_data = {team_id: (key, name, category) for team_id, key, name, category in cursor}
        cursor.execute(f"SELECT u.name, u.username, u.email, u.teamid FROM user u "
                       f"WHERE "
                       f"  u.teamid IN {list_param(team_data)}",
                       tuple(team_data.keys()))
        team_users = {team_id: [] for team_id in team_data.keys()}
        for name, username, email, team_id in cursor:
            team_users[team_id].append(UserDto(login_name=username, display_name=name, email=email))
        return [TeamDto(team_key, team_name, category, team_users[team_id])
                for team_id, (team_key, team_name, category) in team_data.items()]
