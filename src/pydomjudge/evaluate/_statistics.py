import datetime
import itertools
import logging
import math
import statistics
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydomjudge.database import (
    ClarificationDto,
    ContestDataExport,
    SubmissionDto,
    TeamDto,
)
from pydomjudge.exc import InconsistentDataError
from pydomjudge.model import Verdict

log = logging.getLogger(__name__)


def _runtime(submission: SubmissionDto) -> float:
    runtime = submission.maximum_runtime
    assert runtime is not None
    return runtime


def all_false(_: Any) -> bool:
    return False


@dataclass
class ProblemGroupStatistics:
    submission_count: int
    correct_submission_count: int
    teams_with_attempt: set[str]
    teams_with_solution: set[str]
    submissions_until_correct_by_team: dict[str, int]

    first_teams: list[tuple[str, SubmissionDto]]
    fastest_teams: list[tuple[str, SubmissionDto]]
    shortest_teams: list[tuple[str, SubmissionDto]]
    smallest_teams: list[tuple[str, SubmissionDto]]

    verdict_count: dict[Verdict, int]
    verdicts_by_time: dict[Verdict, list[float]]

    @classmethod
    def of(cls, submissions: list[SubmissionDto]):
        correct_submissions = [
            submission
            for submission in submissions
            if submission.verdict == Verdict.CORRECT
        ]
        submission_count: int = len(submissions)
        correct_submission_count: int = len(correct_submissions)
        teams_with_attempt: set[str] = set(
            submission.team_name for submission in submissions
        )
        teams_with_solution: set[str] = set(
            submission.team_name for submission in correct_submissions
        )

        submissions_by_team = defaultdict(list)
        for submission in submissions:
            submissions_by_team[submission.team_name].append(submission)

        submissions_by_team_sorted = {
            team_key: sorted(team_submissions, key=lambda s: s.submission_time)
            for team_key, team_submissions in submissions_by_team.items()
        }

        correct_submissions_by_team = {}
        for team_key, team_submissions in submissions_by_team_sorted.items():
            correct_submissions = [
                submission
                for submission in team_submissions
                if submission.verdict == Verdict.CORRECT
            ]
            if correct_submissions:
                correct_submissions_by_team[team_key] = correct_submissions

        first_correct_submission_by_team: dict[str, SubmissionDto] = {
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
        # Only submissions with recorded runs have a runtime
        timed_correct_submissions_by_team = {
            team_key: timed
            for team_key, team_submissions in correct_submissions_by_team.items()
            if (timed := [s for s in team_submissions if s.maximum_runtime is not None])
        }
        fastest_correct_submission_by_team: dict[str, SubmissionDto] = {
            team_key: min(team_submissions, key=_runtime)
            for team_key, team_submissions in timed_correct_submissions_by_team.items()
        }
        fastest_teams = sorted(
            fastest_correct_submission_by_team.items(),
            key=lambda item: _runtime(item[1]),
        )
        shortest_correct_submission_by_team: dict[str, SubmissionDto] = {
            team_key: min(team_submissions, key=lambda s: s.line_count)
            for team_key, team_submissions in correct_submissions_by_team.items()
        }
        shortest_teams = sorted(
            list(shortest_correct_submission_by_team.items()),
            key=lambda item: item[1].line_count,
        )
        smallest_correct_submission_by_team: dict[str, SubmissionDto] = {
            team_key: min(team_submissions, key=lambda s: s.byte_size)
            for team_key, team_submissions in correct_submissions_by_team.items()
        }
        smallest_teams = sorted(
            list(smallest_correct_submission_by_team.items()),
            key=lambda item: item[1].byte_size,
        )

        verdict_count: dict[Verdict, int] = defaultdict(int)
        verdicts_by_time: dict[Verdict, list[float]] = defaultdict(list)
        for submission in submissions:
            if submission.verdict is None:  # still pending
                continue
            verdicts_by_time[submission.verdict].append(submission.submission_time)
            verdict_count[submission.verdict] += 1

        return cls(
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


@dataclass
class ProblemStatistics:
    by_language: dict[str, ProblemGroupStatistics]
    overall: ProblemGroupStatistics

    @classmethod
    def of(cls, submissions: list[SubmissionDto]):
        submissions_by_language = defaultdict(list)
        for submission in submissions:
            submissions_by_language[submission.language_key].append(submission)

        by_language = {
            language_key: ProblemGroupStatistics.of(language_submissions)
            for language_key, language_submissions in submissions_by_language.items()
        }
        overall = ProblemGroupStatistics.of(submissions)
        return cls(by_language=by_language, overall=overall)


@dataclass
class ContestStatistics:
    team_name_by_key: dict[str, str]
    language_name_by_key: dict[str, str]
    problem_statistics_by_key: dict[str, ProblemStatistics]

    @classmethod
    def of(
        cls,
        contest_data: ContestDataExport,
        team_filter: Callable[[TeamDto], bool] | None = None,
    ):
        if team_filter is None:

            def team_filter(_: TeamDto) -> bool:
                return True

        team_name_by_key = {
            team.name: team.display_name
            for team in contest_data.teams.values()
            if team_filter(team)
        }
        language_name_by_key = contest_data.languages

        submissions = [
            submission
            for submission in contest_data.submissions
            if not submission.too_late and submission.team_name in team_name_by_key
        ]
        submissions_by_problem = defaultdict(list)
        for submission in submissions:
            problem = contest_data.problems[submission.contest_problem_key]
            submissions_by_problem[problem].append(submission)

        problem_statistics_by_key: dict[str, ProblemStatistics] = {
            problem_key: ProblemStatistics.of(submissions)
            for problem_key, submissions in submissions_by_problem.items()
        }
        return cls(
            team_name_by_key=team_name_by_key,
            language_name_by_key=language_name_by_key,
            problem_statistics_by_key=problem_statistics_by_key,
        )


@dataclass
class SummaryStatistics:
    contest_keys: list[str]

    total_active_users: int
    total_contest_count: int
    total_problem_count: int
    total_solved_problem_count: int
    total_submission_count: int
    total_lines_of_code: int
    total_clarification_count: int

    # In minutes; None without answered clarifications
    average_clarification_time: float | None
    median_clarification_time: float | None
    average_submissions_per_contest: float
    average_clarifications_per_contest: float

    minimum_solution_line_count: int

    submissions_per_day: list[int]
    submissions_per_hour: list[int]
    submissions_per_day_hour: list[list[int]]
    submissions_by_time_remaining: list[int]
    submissions_by_contest: dict[str, int]
    submissions_by_problem: dict[str, int]
    submissions_by_language: dict[str, int]
    submissions_by_language_correct: dict[str, int]

    clarifications_per_day: list[int]
    clarifications_per_hour: list[int]
    clarifications_by_contest: dict[str, int]
    clarification_response_times: list[float]
    clarifications_by_key: dict[str, ClarificationDto]
    clarifications_by_problem: dict[str, int]

    @classmethod
    def of(
        cls,
        contests_data: list[ContestDataExport],
        timezone: datetime.tzinfo,
        submission_filter=None,
    ) -> "SummaryStatistics":
        if not contests_data:
            raise InconsistentDataError("No contests given")
        for contest_data in contests_data:
            if contest_data.description.start is None:
                raise InconsistentDataError(
                    f"Given contest {contest_data.description.contest_key} has no start time"
                )
            if contest_data.description.end is None:
                raise InconsistentDataError(
                    f"Given contest {contest_data.description.contest_key} has no end time"
                )

        # Sorted copy, the caller's list stays as it is
        contests_data = sorted(
            contests_data, key=lambda contest_data: contest_data.description.start or 0
        )
        contest_data_by_key = {
            contest_data.description.contest_key: contest_data
            for contest_data in contests_data
        }

        all_clarifications: list[ClarificationDto] = list(
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
        smallest_solution_by_problem = {}

        submissions_per_day = [0] * 7
        submissions_per_hour = [0] * 24
        submissions_per_day_hour = [[0] * 24 for _ in range(7)]
        submissions_per_contest = defaultdict(int)
        submissions_by_problem = defaultdict(int)
        submissions_by_language = defaultdict(int)
        submissions_by_language_correct = defaultdict(int)
        submissions_by_time_remaining = [0] * 10

        for submission in all_submissions:
            if submission.too_late:
                continue
            if not submission.is_source_submission:
                continue
            submission_team = contest_data_by_key[submission.contest_key].teams[
                submission.team_name
            ]
            if submission_filter is not None and not submission_filter(
                submission, submission_team
            ):
                continue

            contest_description = contest_data_by_key[
                submission.contest_key
            ].description
            contest_start = contest_description.start
            contest_end = contest_description.end
            assert contest_start is not None and contest_end is not None

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
            active_users.update(set(submission_team.member_login_names))

            remaining = (contest_end - submission.submission_time) / (
                contest_end - contest_start
            )
            # 0 for the last tenth of the contest; a submission right at the
            # start would otherwise land in a non-existent eleventh bucket
            submissions_by_time_remaining[min(max(int(remaining * 10), 0), 9)] += 1

            if submission.verdict == Verdict.CORRECT:
                submissions_by_language_correct[submission.language_key] += 1
                solved_problems.add(problem_unique_key)
                smallest_solution_by_problem[problem_unique_key] = min(
                    smallest_solution_by_problem.get(problem_unique_key, math.inf),
                    submission.line_count,
                )

        clarifications_per_day = [0] * 7
        clarifications_per_hour = [0] * 24
        clarifications_per_contest = defaultdict(int)
        clarification_response_times: list[float] = []
        clarifications_by_key = {
            clarification.identifier: clarification
            for clarification in all_clarifications
        }
        clarifications_by_problem = defaultdict(int)

        clarification_responses = {
            clarifications_by_key[
                clarification.response_to
            ].identifier: clarification.identifier
            for clarification in all_clarifications
            if clarification.response_to is not None
        }

        for clarification in all_clarifications:
            if (
                clarification.from_jury
                or clarification.identifier not in clarification_responses
            ):
                continue
            contest_data = contest_data_by_key[clarification.contest_key]
            description = contest_data.description
            assert description.start is not None and description.end is not None
            if description.start <= clarification.request_time <= description.end:
                response = clarifications_by_key[
                    clarification_responses[clarification.identifier]
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

        average_clarification_time = (
            statistics.mean(clarification_response_times) / 60
            if clarification_response_times
            else None
        )
        median_clarification_time = (
            statistics.median(clarification_response_times) / 60
            if clarification_response_times
            else None
        )
        # Over all contests, also those without submissions or clarifications
        average_submissions_per_contest = sum(submissions_per_contest.values()) / len(
            contests_data
        )
        average_clarifications_per_contest = sum(
            clarifications_per_contest.values()
        ) / len(contests_data)

        return cls(
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
