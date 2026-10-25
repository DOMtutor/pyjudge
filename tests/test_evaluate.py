"""Statistics and plots of exported contests."""

import datetime
import pathlib
from zoneinfo import ZoneInfo

import matplotlib.pyplot as plt

from pydomjudge.database import ContestDataExport
from pydomjudge.evaluate import ContestStatistics, ProblemRenderer, SummaryStatistics
from pydomjudge.model import Verdict

TZ = ZoneInfo("Europe/Berlin")


def _with_submissions(export: ContestDataExport, **changes) -> ContestDataExport:
    """The fixture's first submission (time-limit), modified, plus a pending one."""
    first, pending = export.submissions
    return export.model_copy(
        update={"submissions": [first.model_copy(update=changes), pending]}
    )


def test_summary_without_answered_clarifications(contest_export: ContestDataExport):
    exports = [contest_export]
    summary = SummaryStatistics.of(exports, TZ)
    assert exports == [contest_export]  # not reordered in place
    assert summary.average_clarification_time is None
    assert summary.median_clarification_time is None
    assert summary.total_submission_count == 2
    assert summary.average_submissions_per_contest == 2
    assert sum(summary.submissions_by_time_remaining) == 2


def test_submission_at_contest_start_is_counted(contest_export: ContestDataExport):
    export = _with_submissions(contest_export, submission_time=0.0)
    summary = SummaryStatistics.of([export], TZ)
    assert summary.submissions_by_time_remaining[9] == 2


def test_contest_statistics_with_correct_submission_without_runs(
    contest_export: ContestDataExport,
):
    export = _with_submissions(contest_export, verdict=Verdict.CORRECT, case_result=[])
    statistics = ContestStatistics.of(export)
    overall = statistics.problem_statistics_by_key["p"].overall
    assert overall.correct_submission_count == 1
    assert overall.teams_with_solution == {"t"}
    assert overall.fastest_teams == []  # no runtime known
    assert overall.verdict_count == {Verdict.CORRECT: 1}  # pending one skipped


def test_render_closes_figures(
    contest_export: ContestDataExport, tmp_path: pathlib.Path
):
    statistics = ContestStatistics.of(contest_export)
    start = datetime.datetime.fromtimestamp(0, TZ)
    renderer = ProblemRenderer(start, start + datetime.timedelta(days=2))
    target = tmp_path / "p.png"
    renderer.render_problem_submission_statistics(
        statistics.problem_statistics_by_key["p"], target
    )
    assert target.read_bytes().startswith(b"\x89PNG")
    assert plt.get_fignums() == []
