import datetime
import logging
import math
import pathlib
from typing import List

import matplotlib
import matplotlib.ticker
import matplotlib.pyplot as plt
import numpy as np

from pydomjudge.evaluate.statistics import ProblemStatistics, SummaryStatistics
from pydomjudge.model import Verdict

verdict_formats = [
    ({Verdict.CORRECT}, {"label": "AC", "color": "green"}),
    ({Verdict.WRONG_ANSWER}, {"label": "WA", "color": "red"}),
    ({Verdict.RUN_ERROR}, {"label": "RTE", "color": "orange"}),
    ({Verdict.TIME_LIMIT}, {"label": "TLE", "color": "purple"}),
]
fallback_format = {"label": "Other", "color": "gray"}


class ProblemRenderer(object):
    def __init__(self, start_time: datetime.datetime, end_time: datetime.datetime):
        self.start_time = start_time
        self.end_time = end_time

        start_day = start_time.replace(hour=0, minute=0, second=0, microsecond=0)
        delta = datetime.timedelta(days=1.0)

        while start_day < start_time:
            start_day += delta
        self.start_day = start_day

        days = []
        while start_day <= end_time:
            days.append(start_day)
            start_day += delta

        # if len(days) > 7:
        #     days = days[:: len(days) // 7]
        self.day_seconds = days

        self.start_second = int(start_time.timestamp())
        self.end_second = int(end_time.timestamp())
        self.day_beginning_seconds = [
            int(day.timestamp()) - self.start_second for day in days
        ]
        self.day_names = [day.strftime("%d.%m.%y") for day in days]

        self.seconds_per_bucket = (
            3600 * 6 * (2 ** (int(math.ceil(math.log(len(days)) / math.log(7)))))
        )
        self.submission_buckets = (
            self.end_second - self.start_second
        ) // self.seconds_per_bucket + 1

    def render_problem_submission_statistics(
        self, problem_stats: ProblemStatistics, file: pathlib.Path
    ):
        x_axis = np.arange(0, stop=self.submission_buckets)

        verdict_data = {verdict: np.zeros(len(x_axis)) for verdict in Verdict}
        for (
            verdict,
            timestamps,
        ) in problem_stats.overall.verdicts_by_time.items():
            for timestamp in timestamps:
                x_pos = (int(timestamp) - self.start_second) // self.seconds_per_bucket
                if not 0 <= x_pos < self.submission_buckets:
                    logging.warning(
                        "Invalid submission time %f (should be between %s and %s)",
                        timestamp,
                        self.start_time,
                        self.end_time,
                    )
                    continue
                verdict_data[verdict][x_pos] += 1

        fig, ax = plt.subplots()

        graph_data = []
        handled_verdicts = set()
        for verdicts, verdict_format in verdict_formats:
            handled_verdicts.update(verdicts)
            values = sum(verdict_data[verdict] for verdict in verdicts)
            if values.any():
                graph_data.append(
                    (values, verdict_format["label"], verdict_format["color"])
                )
        if len(Verdict) > len(handled_verdicts):
            other_verdict_values = sum(
                verdict_data[verdict]
                for verdict in Verdict
                if verdict not in handled_verdicts
            )
            if other_verdict_values.any():
                graph_data.append(
                    (
                        other_verdict_values,
                        fallback_format["label"],
                        fallback_format["color"],
                    )
                )

        summed = np.zeros(len(x_axis))
        for value, label, color in graph_data:
            ax.bar(
                x_axis * self.seconds_per_bucket + self.seconds_per_bucket // 2,
                value,
                width=int(math.ceil(self.seconds_per_bucket * 0.8)),
                label=label,
                color=color,
                bottom=summed,
            )
            summed += value
        ax.set_xlim((-1, self.submission_buckets * self.seconds_per_bucket))
        ax.legend()
        ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))

        if len(self.day_names) <= 7:
            ticks = self.day_beginning_seconds
            labels = self.day_names
        else:
            idx = np.round(np.linspace(0, len(self.day_names) - 1, 7)).astype(int)
            ticks = [self.day_beginning_seconds[i] for i in idx]
            labels = [self.day_names[i] for i in idx]
        plt.xticks(ticks=ticks, labels=labels)

        with file.open(mode="wb") as f:
            plt.savefig(f, format="png", transparent=True)


class SummaryRenderer(object):
    def __init__(self, data: SummaryStatistics):
        self.data = data

    def render_per_day(self, path: pathlib.Path, day_labels: List[str]):
        fig, ax = plt.subplots()
        per_day_x_axis = np.arange(len(day_labels))
        per_day_width = 0.25

        ax.bar(
            per_day_x_axis,
            self.data.submissions_per_day,
            width=per_day_width,
            color="orange",
            label="Submissions",
        )
        ax.bar(
            per_day_x_axis + per_day_width,
            self.data.clarifications_per_day,
            width=per_day_width,
            color="teal",
            label="Clarifications",
        )

        ax.legend()
        ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        ax.set_xticks(per_day_x_axis + per_day_width / 2)
        ax.set_xticklabels(day_labels)

        with path.open(mode="wb") as f:
            plt.savefig(f, format="png", transparent=True)

    def render_per_hour(self, path: pathlib.Path):
        fig, ax = plt.subplots()
        per_hour_x_axis = np.arange(24)
        per_hour_width = 0.25

        ax.bar(
            per_hour_x_axis,
            self.data.submissions_per_hour,
            width=per_hour_width,
            color="orange",
            label="Submissions",
        )
        ax.bar(
            per_hour_x_axis + per_hour_width,
            self.data.clarifications_per_hour,
            width=per_hour_width,
            color="teal",
            label="Clarifications",
        )
        ax.legend()
        ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        ax.set_xticks(per_hour_x_axis + per_hour_width / 2)
        ax.set_xticklabels(per_hour_x_axis)

        with path.open(mode="wb") as f:
            plt.savefig(f, format="png", transparent=True)

    def render_per_day_hour(self, path: pathlib.Path, day_labels: List[str]):
        fig, ax = plt.subplots(figsize=(9, 3))
        im = ax.imshow(self.data.submissions_per_day_hour)
        ax.set_xticks(np.arange(24))
        ax.set_yticks(np.arange(len(day_labels)))
        ax.set_yticklabels(day_labels)
        ax.spines[:].set_visible(False)

        formatter = matplotlib.ticker.StrMethodFormatter("{x:d}")
        for day, hour_submissions in enumerate(self.data.submissions_per_day_hour):
            for hour, count in enumerate(hour_submissions):
                im.axes.text(
                    hour,
                    day,
                    formatter(count),
                    horizontalalignment="center",
                    verticalalignment="center",
                    color="white",
                )

        cbar = ax.figure.colorbar(im, ax=ax)
        cbar.ax.set_ylabel("Submissions", rotation=-90, va="bottom")
        fig.tight_layout()

        with path.open(mode="wb") as f:
            plt.savefig(f, format="png", transparent=True)

    def render_per_remaining_time(self, path: pathlib.Path):
        fig, ax = plt.subplots()
        ax.bar(
            range(len(self.data.submissions_by_time_remaining)),
            self.data.submissions_by_time_remaining,
            width=0.4,
            color="orange",
            label="Submissions",
        )
        ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        ax.set_xticks(np.arange(len(self.data.submissions_by_time_remaining)))
        ax.set_xticklabels([f"{i:d}%" for i in range(100, 0, -10)])

        with path.open(mode="wb") as f:
            plt.savefig(f, format="png", transparent=True)

    def render_per_contest(self, path: pathlib.Path):
        fig, ax = plt.subplots()
        per_contest_x_axis = np.arange(len(self.data.contest_keys))
        per_contest_width = 0.25

        ax.bar(
            per_contest_x_axis,
            [
                self.data.submissions_by_contest[contest_key]
                for contest_key in self.data.contest_keys
            ],
            width=per_contest_width,
            color="orange",
            label="Submissions",
        )
        ax.bar(
            per_contest_x_axis + per_contest_width,
            [
                self.data.clarifications_by_contest[contest_key]
                for contest_key in self.data.contest_keys
            ],
            width=per_contest_width,
            color="teal",
            label="Clarifications",
        )
        ax.legend()
        ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        ax.set_xticks(per_contest_x_axis + per_contest_width / 2)
        ax.set_xticklabels(self.data.contest_keys, rotation=-30)

        with path.open(mode="wb") as f:
            plt.savefig(f, format="png", transparent=True)

    def render_per_language(self, path: pathlib.Path):
        fig, ax = plt.subplots()
        submissions_by_language_x_axis = np.arange(
            len(self.data.submissions_by_language.keys())
        )
        submissions_by_language_width = 0.25
        per_contest_width = 0.25

        language_keys = sorted(list(self.data.submissions_by_language.keys()))
        language_submissions_correct = []
        language_submissions_incorrect = []
        for language_key in language_keys:
            correct_submissions = self.data.submissions_by_language_correct[
                language_key
            ]
            language_submissions_correct.append(correct_submissions)
            language_submissions_incorrect.append(
                self.data.submissions_by_language[language_key] - correct_submissions
            )

        ax.bar(
            submissions_by_language_x_axis,
            language_submissions_correct,
            width=submissions_by_language_width,
            color="green",
            label="Correct",
        )
        ax.bar(
            submissions_by_language_x_axis + submissions_by_language_width,
            language_submissions_incorrect,
            width=submissions_by_language_width,
            color="red",
            label="Wrong",
        )  # bottom=submissions_by_language_correct
        ax.legend()
        ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        ax.set_xticks(submissions_by_language_x_axis + per_contest_width / 2)
        ax.set_xticklabels(language_keys)

        with path.open(mode="wb") as f:
            plt.savefig(f, format="png", transparent=True)
