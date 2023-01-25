import dataclasses
import datetime
import itertools
import math
import statistics
from collections import defaultdict
from typing import Set, Dict, List

import pytz

from pyjudge.data.submission import SubmissionDto, ContestDataDto
from pyjudge.model import Verdict


@dataclasses.dataclass
class ProblemGroupStatistics(object):
    submission_count: int
    correct_submission_count: int
    teams_with_attempt: Set[str]
    teams_with_solution: Set[str]
    submissions_until_correct_by_team: Dict[str, int]

    first_teams: List[str]
    fastest_teams: List[str]
    shortest_teams: List[str]
    smallest_teams: List[str]

    verdict_count: Dict[Verdict, int]
    verdicts_by_time: Dict[Verdict, List[float]]

    @staticmethod
    def of(submissions: List[SubmissionDto]):
        correct_submissions = [
            submission
            for submission in submissions
            if submission.verdict == Verdict.CORRECT
        ]
        submission_count: int = len(submissions)
        correct_submission_count: int = len(correct_submissions)
        teams_with_attempt: Set[str] = set(
            submission.team_key for submission in submissions
        )
        teams_with_solution: Set[str] = set(
            submission.team_key for submission in correct_submissions
        )

        submissions_by_team = defaultdict(list)
        for submission in submissions:
            submissions_by_team[submission.team_key].append(submission)

        submissions_by_team_sorted = {
            team_key: sorted(team_submissions, key=lambda s: s.submission_time)
            for team_key, team_submissions in submissions_by_team.items()
        }

        correct_submissions_by_team = dict()
        for team_key, team_submissions in submissions_by_team_sorted.items():
            correct_submissions = [
                submission
                for submission in team_submissions
                if submission.verdict == Verdict.CORRECT
            ]
            if correct_submissions:
                correct_submissions_by_team[team_key] = correct_submissions

        first_correct_submission_by_team: Dict[str, SubmissionDto] = {
            team_key: min(team_submissions, key=lambda s: s.submission_time)
            for team_key, team_submissions in correct_submissions_by_team.items()
        }
        submissions_until_correct_by_team = {
            team_key: len(
                [
                    submission
                    for submission in submissions_by_team_sorted[team_key]
                    if submission.submission_time
                    <= team_correct_submission.submission_time
                ]
            )
            for team_key, team_correct_submission in first_correct_submission_by_team.items()
        }

        first_teams = sorted(
            list(first_correct_submission_by_team.items()),
            key=lambda item: item[1].submission_time,
        )
        fastest_correct_submission_by_team: Dict[str, SubmissionDto] = {
            team_key: min(team_submissions, key=lambda s: s.maximum_runtime)
            for team_key, team_submissions in correct_submissions_by_team.items()
        }
        fastest_teams = sorted(
            list(fastest_correct_submission_by_team.items()),
            key=lambda item: item[1].maximum_runtime,
        )
        shortest_correct_submission_by_team: Dict[str, SubmissionDto] = {
            team_key: min(team_submissions, key=lambda s: s.line_count)
            for team_key, team_submissions in correct_submissions_by_team.items()
        }
        shortest_teams = sorted(
            list(shortest_correct_submission_by_team.items()),
            key=lambda item: item[1].line_count,
        )
        smallest_correct_submission_by_team: Dict[str, SubmissionDto] = {
            team_key: min(team_submissions, key=lambda s: s.byte_size)
            for team_key, team_submissions in correct_submissions_by_team.items()
        }
        smallest_teams = sorted(
            list(smallest_correct_submission_by_team.items()),
            key=lambda item: item[1].byte_size,
        )

        verdict_count: Dict[Verdict, int] = defaultdict(lambda: 0)
        verdicts_by_time: Dict[Verdict, List[float]] = defaultdict(list)
        for submission in submissions:
            verdicts_by_time[submission.verdict].append(submission.submission_time)

        return ProblemGroupStatistics(
            submission_count=submission_count,
            correct_submission_count=correct_submission_count,
            teams_with_attempt=teams_with_attempt,
            teams_with_solution=teams_with_solution,
            submissions_until_correct_by_team=submissions_until_correct_by_team,
            first_teams=first_teams,
            fastest_teams=fastest_teams,
            shortest_teams=shortest_teams,
            smallest_teams=smallest_teams,
            verdict_count=verdict_count,
            verdicts_by_time=verdicts_by_time,
        )


@dataclasses.dataclass
class ProblemStatistics(object):
    by_language: Dict[str, ProblemGroupStatistics]
    overall: ProblemGroupStatistics

    @staticmethod
    def of(submissions: List[SubmissionDto]):
        submissions_by_language = defaultdict(list)
        for submission in submissions:
            submissions_by_language[submission.language_key].append(submission)

        by_language = {
            language_key: ProblemGroupStatistics.of(language_submissions)
            for language_key, language_submissions in submissions_by_language.items()
        }
        overall = ProblemGroupStatistics.of(submissions)
        return ProblemStatistics(by_language=by_language, overall=overall)


@dataclasses.dataclass
class ContestStatistics(object):
    team_name_by_key: Dict[str, str]
    language_name_by_key: Dict[str, str]
    problem_statistics_by_key: Dict[str, ProblemStatistics]

    @staticmethod
    def of(contest_data: ContestDataDto):
        team_name_by_key = {
            team.key: team.display_name for team in contest_data.teams.values()
        }
        language_name_by_key = contest_data.languages

        submissions = [
            submission
            for submission in contest_data.submissions
            if not submission.too_late
        ]
        submissions_by_problem = defaultdict(list)
        for submission in submissions:
            problem = contest_data.problems[submission.contest_problem_key]
            submissions_by_problem[problem].append(submission)

        problem_statistics_by_key: Dict[str, ProblemStatistics] = {
            problem_key: ProblemStatistics.of(submissions)
            for problem_key, submissions in submissions_by_problem.items()
        }
        return ContestStatistics(
            team_name_by_key=team_name_by_key,
            language_name_by_key=language_name_by_key,
            problem_statistics_by_key=problem_statistics_by_key,
        )


@dataclasses.dataclass
class SummaryStatistics(object):
    contest_keys: List[str]

    total_active_users: int
    total_contest_count: int
    total_problem_count: int
    total_solved_problem_count: int
    total_submission_count: int
    total_lines_of_code: int
    total_clarification_count: int

    average_clarification_time: float
    median_clarification_time: float
    average_submissions_per_contest: float
    average_clarifications_per_contest: float

    minimum_solution_line_count: int

    submissions_per_day: List[int]
    submissions_per_hour: List[int]
    submissions_per_day_hour: List[List[int]]
    submissions_by_time_remaining: List[int]
    submissions_by_contest: Dict[str, int]
    submissions_by_problem: Dict[str, int]
    submissions_by_language: Dict[str, int]
    submissions_by_language_correct: Dict[str, int]

    clarifications_per_day: List[int]
    clarifications_per_hour: List[int]
    clarifications_by_contest: Dict[str, int]
    clarification_response_times: List[int]
    clarifications_by_key: Dict[str, int]
    clarifications_by_problem: Dict[str, int]

    @staticmethod
    def of(
        contests_data: List[ContestDataDto],
        timezone: pytz.BaseTzInfo,
        submission_filter=None,
    ) -> "SummaryStatistics":
        contests_data.sort(key=lambda contest_data: contest_data.description.start)
        contest_data_by_key = {
            contest_data.description.contest_key: contest_data
            for contest_data in contests_data
        }

        all_clarifications = list(
            itertools.chain(
                *[contest_data.clarifications for contest_data in contests_data]
            )
        )
        all_submissions = list(
            itertools.chain(
                *[contest_data.submissions for contest_data in contests_data]
            )
        )

        contest_keys = [
            contest_data.description.contest_key for contest_data in contests_data
        ]
        solved_problems = set()
        active_users = set()
        smallest_solution_by_problem = dict()

        submissions_per_day = [0] * 7
        submissions_per_hour = [0] * 24
        submissions_per_day_hour = [[0] * 24 for _ in range(7)]
        submissions_per_contest = defaultdict(lambda: 0)
        submissions_by_problem = defaultdict(lambda: 0)
        submissions_by_language = defaultdict(lambda: 0)
        submissions_by_language_correct = defaultdict(lambda: 0)
        submissions_by_time_remaining = [0] * 10

        for submission in all_submissions:
            if submission.too_late:
                continue
            if not submission.is_source_submission:
                continue
            submission_team = contest_data_by_key[submission.contest_key].teams[
                submission.team_key
            ]
            if submission_team is None:
                continue
            if submission_filter is not None and not submission_filter(
                submission, submission_team
            ):
                continue

            problem_unique_key = (
                submission.contest_key,
                submission.contest_problem_key,
            )
            submission_time = datetime.datetime.fromtimestamp(
                submission.submission_time, timezone
            )
            submissions_per_day[submission_time.weekday()] += 1
            submissions_per_hour[submission_time.hour] += 1
            submissions_per_day_hour[submission_time.weekday()][
                submission_time.hour
            ] += 1
            submissions_per_contest[submission.contest_key] += 1
            submissions_by_problem[problem_unique_key] += 1
            submissions_by_language[submission.language_key] += 1
            active_users.update(
                set(user.login_name for user in submission_team.members)
            )

            contest_description = contest_data_by_key[
                submission.contest_key
            ].description
            contest_start = contest_description.start
            contest_end = contest_description.end
            submissions_by_time_remaining[
                int(
                    (
                        (contest_end - submission.submission_time)
                        / (contest_end - contest_start)
                    )
                    * 10
                )
            ] += 1

            if submission.verdict == Verdict.CORRECT:
                submissions_by_language_correct[submission.language_key] += 1
                solved_problems.add(problem_unique_key)
                smallest_solution_by_problem[problem_unique_key] = min(
                    smallest_solution_by_problem.get(problem_unique_key, math.inf),
                    submission.line_count,
                )

        clarifications_per_day = [0] * 7
        clarifications_per_hour = [0] * 24
        clarifications_per_contest = defaultdict(lambda: 0)
        clarification_response_times = []
        clarifications_by_key = {
            clarification.key: clarification for clarification in all_clarifications
        }
        clarifications_by_problem = defaultdict(lambda: 0)

        clarification_responses = {
            clarifications_by_key[clarification.response_to].key: clarification.key
            for clarification in all_clarifications
            if clarification.response_to is not None
        }

        for clarification in all_clarifications:
            if (
                clarification.from_jury
                or clarification.key not in clarification_responses
            ):
                continue
            contest_data = contest_data_by_key[clarification.contest_key]
            description = contest_data.description
            if description.start <= clarification.request_time <= description.end:
                response = clarifications_by_key[
                    clarification_responses[clarification.key]
                ]
                if description.start <= response.request_time <= description.end:
                    clarification_time = datetime.datetime.fromtimestamp(
                        clarification.request_time, timezone
                    )
                    clarifications_per_day[clarification_time.weekday()] += 1
                    clarifications_per_hour[clarification_time.hour] += 1
                    clarifications_per_contest[clarification.contest_key] += 1

                    clarification_response_times.append(
                        response.request_time - clarification.request_time
                    )
                    clarifications_by_problem[
                        (clarification.contest_key, clarification.contest_problem_key)
                    ] += 1

        average_clarification_time = statistics.mean(clarification_response_times) / 60
        median_clarification_time = statistics.median(clarification_response_times) / 60
        average_submissions_per_contest = statistics.mean(
            submissions_per_contest.values()
        )
        average_clarifications_per_contest = statistics.mean(
            clarifications_per_contest.values()
        )

        return SummaryStatistics(
            contest_keys=contest_keys,
            total_active_users=len(active_users),
            total_contest_count=len(contest_keys),
            total_problem_count=sum(
                len(contest_data.problems) for contest_data in contests_data
            ),
            total_solved_problem_count=len(solved_problems),
            total_submission_count=sum(
                len(contest_data.submissions) for contest_data in contests_data
            ),
            total_lines_of_code=sum(
                submission.line_count for submission in all_submissions
            ),
            total_clarification_count=sum(
                len(contest_data.clarifications) for contest_data in contests_data
            ),
            average_clarification_time=average_clarification_time,
            median_clarification_time=median_clarification_time,
            average_submissions_per_contest=average_submissions_per_contest,
            average_clarifications_per_contest=average_clarifications_per_contest,
            minimum_solution_line_count=sum(smallest_solution_by_problem.values()),
            submissions_per_day=submissions_per_day,
            submissions_per_hour=submissions_per_hour,
            submissions_per_day_hour=submissions_per_day_hour,
            submissions_by_time_remaining=submissions_by_time_remaining,
            submissions_by_contest=submissions_per_contest,
            submissions_by_problem=submissions_by_problem,
            submissions_by_language=submissions_by_language,
            submissions_by_language_correct=submissions_by_language_correct,
            clarifications_by_key=clarifications_by_key,
            clarifications_per_day=clarifications_per_day,
            clarifications_per_hour=clarifications_per_hour,
            clarifications_by_contest=clarifications_per_contest,
            clarification_response_times=clarification_response_times,
            clarifications_by_problem=clarifications_by_problem,
        )
