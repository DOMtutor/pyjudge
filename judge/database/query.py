from collections import defaultdict
from typing import List, Dict, Collection

from mysql.connector.cursor import MySQLCursor

from judge.data.submission import ParticipantSubmission
from .util import get_unique, list_param, Database
from judge.model import Contest, ContestProblem, Team, Verdict


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


def find_valid_submissions(database: Database,
                           contest: Contest,
                           teams: List[Team]) -> List[ParticipantSubmission]:
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        contest_id, problem_name_by_id = _find_contest_with_problems(cursor, contest)
        cursor.execute(f"SELECT p.probid, j.result, s.submittime, t.name FROM problem p, team t "
                       f"  JOIN submission s ON t.teamid = s.teamid AND p.probid = s.probid "
                       f"  JOIN judging j ON j.submitid = s.submitid "
                       f"WHERE "
                       f"  j.valid = 1 AND "
                       f"  p.probid IN {list_param(problem_name_by_id)} AND "
                       f"  t.name IN {list_param(teams)}",
                       (*problem_name_by_id.keys(), *(team.name for team in teams), contest_id,))

        teams_by_name = {team.name: team for team in teams}
        contest_problem_by_name = {contest_problem.name: contest_problem for contest_problem in contest.problems}
        submissions = [ParticipantSubmission(teams_by_name[team_name],
                                             contest_problem_by_name[problem_name_by_id[problem_id]],
                                             parse_judging_verdict(result),
                                             submission_time)
                       for problem_id, result, submission_time, team_name in cursor]
    return submissions


# TODO
def find_clarifications(database: Database,
                        contest: Contest,
                        teams: List[Team],
                        clarification_patterns: List[str]) -> Dict[Team, Collection[ContestProblem]]:
    with database.transaction_cursor(readonly=True, prepared_cursor=True) as cursor:
        contest_id, problem_name_by_id = _find_contest_with_problems(cursor, contest)
        cursor.execute(f"SELECT p.probid, t.name FROM problem p, team t "
                       f"  JOIN clarification c ON t.teamid = c.recipient "
                       f"WHERE "
                       f"  c.probid = p.probid AND "
                       f"  p.probid IN {list_param(problem_name_by_id)} AND "
                       f"  t.name IN {list_param(teams)} AND "
                       f"  c.answered AND "
                       f"  ({' OR '.join(['c.body LIKE ?'] * len(clarification_patterns))})",
                       (*problem_name_by_id.keys(), *(team.name for team in teams),
                        *clarification_patterns))

        teams_by_name = {team.name: team for team in teams}
        contest_problem_by_name = {contest_problem.name: contest_problem for contest_problem in contest.problems}
        team_problems_with_clarifications = defaultdict(set)
        for problem_id, team_name in cursor:
            team = teams_by_name[team_name]
            problem = contest_problem_by_name[problem_name_by_id[problem_id]]
            team_problems_with_clarifications[team].add(problem)
        return team_problems_with_clarifications
