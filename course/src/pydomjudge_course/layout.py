"""The grading layout of a contest export: every submission as files, the
counting one per team and problem, and an evaluation of them.

``build_layout`` writes, below a directory it owns these parts of::

    submissions/<problem>/<team>/<int time>_<id>/<original file names>
    final/<team>/<problem>/<files>   (flatten_single_file: final/<team>/<problem><suffix>)
    evaluation.json

Every submission is kept, also those after the cutoff (plagiarism checks use
them) and those with non-text files (``source`` is False for them). The
counting submission of a team and problem is chosen by a rule, by default the
last one that is not too late. Points, penalties and feedback stay with the
course: ``Evaluation`` only says what was submitted, when, and how it was
judged.

A second call with the same export (by modification time) and the same
deadlines, extensions, rule and flattening loads evaluation.json and writes
nothing; otherwise ``submissions/`` and ``final/`` are rebuilt from scratch.
"""

import dataclasses
import datetime
import hashlib
import json
import logging
import os
import pathlib
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Literal

from pydantic import BaseModel

from pydomjudge.database import ContestDataExport, SubmissionDto
from pydomjudge.model import Verdict
from pydomjudge.util import read_str_from

log = logging.getLogger(__name__)

# Changes when the layout or evaluation.json change, so that caches rebuild
LAYOUT_VERSION = 1
EVALUATION_FILE = "evaluation.json"
OWNED = ("submissions", "final")

Timing = Literal["on_time", "late", "too_late"]


@dataclasses.dataclass(frozen=True)
class Deadlines:
    """A submission is on time until end + grace, late (it counts, with the
    course's penalty) until end + late, and too late after that. An extension
    moves the end."""

    end: datetime.datetime
    grace: datetime.timedelta = datetime.timedelta(0)
    late: datetime.timedelta = datetime.timedelta(0)

    def __post_init__(self):
        if self.end.tzinfo is None:
            raise ValueError("The end needs a time zone")
        if not datetime.timedelta(0) <= self.grace <= self.late:
            raise ValueError("Expected 0 <= grace <= late")

    def timing(
        self, time: float, extension: datetime.timedelta = datetime.timedelta(0)
    ) -> Timing:
        moment = datetime.datetime.fromtimestamp(time, datetime.UTC)
        end = self.end + extension
        if moment <= end + self.grace:
            return "on_time"
        if moment <= end + self.late:
            return "late"
        return "too_late"


class SubmissionRecord(BaseModel, frozen=True):
    id: str
    folder: str
    """Relative to the layout directory."""
    files: list[str]
    language: str
    time: float
    timing: Timing
    verdict: Verdict | None
    solved_samples: bool
    """Results are present and every sample case is correct."""
    solved: bool
    """The verdict is correct."""
    source: bool
    """All files are text."""


class TeamProblem(BaseModel):
    submissions: list[SubmissionRecord]
    """By time."""
    counting: str | None
    """The id of the counting submission, if any."""

    @property
    def counting_submission(self) -> SubmissionRecord | None:
        return next((s for s in self.submissions if s.id == self.counting), None)


class TeamRecord(BaseModel):
    team: str
    """The team name."""
    members: list[str]
    """Logins."""
    category: str | None
    problems: dict[str, TeamProblem]
    """By problem key; problems without submissions are left out."""


class Evaluation(BaseModel):
    contest_key: str
    export_mtime: float | None
    config: str
    """Fingerprint of deadlines, extensions, rule, flattening and layout."""
    teams: dict[str, TeamRecord]
    """By team name; every team of the export, also those without submissions."""

    def counting(self, team: str, problem: str) -> SubmissionRecord | None:
        record = self.teams.get(team)
        entry = record.problems.get(problem) if record else None
        return entry.counting_submission if entry else None

    def graded(self) -> Iterator[tuple[str, str, SubmissionRecord]]:
        """(team, problem, submission) of the counting submissions that solve
        the samples, the ones that get points."""
        for team, record in sorted(self.teams.items()):
            for problem, entry in sorted(record.problems.items()):
                submission = entry.counting_submission
                if submission is not None and submission.solved_samples:
                    yield team, problem, submission


Selection = Callable[[Sequence[SubmissionRecord]], SubmissionRecord | None]


def last_before_cutoff(
    submissions: Sequence[SubmissionRecord],
) -> SubmissionRecord | None:
    """The last submission that is not too late (a late one replaces an
    earlier one that was on time)."""
    counting = [s for s in submissions if s.timing != "too_late"]
    return max(counting, key=lambda s: s.time) if counting else None


def load_evaluation(directory: pathlib.Path) -> Evaluation:
    return Evaluation.model_validate_json((directory / EVALUATION_FILE).read_text())


def _fingerprint(
    deadlines: Deadlines,
    extensions: Mapping[str, datetime.timedelta],
    select: Selection,
    flatten_single_file: bool,
) -> str:
    # A rule is identified by its name, so it should be a named function
    config = {
        "version": LAYOUT_VERSION,
        "end": deadlines.end.isoformat(),
        "grace": deadlines.grace.total_seconds(),
        "late": deadlines.late.total_seconds(),
        "extensions": {k: v.total_seconds() for k, v in sorted(extensions.items())},
        "select": f"{select.__module__}.{getattr(select, '__qualname__', select)}",
        "flatten_single_file": flatten_single_file,
    }
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def _cached(
    directory: pathlib.Path, export_mtime: float | None, config: str
) -> Evaluation | None:
    if export_mtime is None or not (directory / EVALUATION_FILE).is_file():
        return None
    if not all((directory / part).is_dir() for part in OWNED):
        return None
    try:
        evaluation = load_evaluation(directory)
    except ValueError:
        log.info("Rebuilding the grading layout: unreadable %s", EVALUATION_FILE)
        return None
    if evaluation.export_mtime == export_mtime and evaluation.config == config:
        return evaluation
    return None


def _component(name: str, what: str) -> str:
    """A name as one path component."""
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError(f"Cannot use {what} {name!r} as a folder name")
    return name


def _file_names(submission: SubmissionDto) -> list[str]:
    names = []
    for number, file in enumerate(submission.files, start=1):
        name = pathlib.PurePosixPath(file.filename.replace("\\", "/")).name
        if not name or name in {".", ".."} or name in names:
            name = f"file{number}"
        names.append(name)
    return names


def _solved_samples(submission: SubmissionDto) -> bool:
    return bool(submission.case_result) and all(
        result.verdict == Verdict.CORRECT
        for result in submission.case_result
        if result.is_sample
    )


def _copy(source: pathlib.Path, target: pathlib.Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _build(
    export: ContestDataExport,
    root: pathlib.Path,
    *,
    deadlines: Deadlines,
    extensions: Mapping[str, datetime.timedelta],
    select: Selection,
    flatten_single_file: bool,
) -> dict[str, TeamRecord]:
    """Writes submissions/ and final/ below root (a fresh folder)."""
    by_name = {
        name: extensions.get(team.external_id or name, extensions.get(name))
        for name, team in export.teams.items()
    }
    known = {team.external_id or name for name, team in export.teams.items()}
    known |= set(export.teams)
    unknown = [key for key in extensions if key not in known]
    if unknown:
        log.warning("%d extensions are for teams not in the export", len(unknown))
        log.debug("Extensions for unknown teams: %s", unknown)

    grouped: dict[tuple[str, str], list[SubmissionDto]] = defaultdict(list)
    for submission in export.submissions:
        if submission.team_name not in export.teams:
            raise ValueError(f"A submission of an unknown team {submission.team_name}")
        problem = export.problems[submission.contest_problem_key]
        grouped[submission.team_name, problem].append(submission)

    teams = {
        name: TeamRecord(
            team=name,
            members=list(team.member_login_names),
            category=team.category_name,
            problems={},
        )
        for name, team in export.teams.items()
    }
    for (team, problem), submissions in sorted(grouped.items()):
        extension = by_name[team] or datetime.timedelta(0)
        ordered = sorted(
            enumerate(submissions), key=lambda p: (p[1].submission_time, p[0])
        )
        records = []
        for position, (_, submission) in enumerate(ordered, start=1):
            identifier = _component(
                submission.external_id or f"n{position}", "submission id"
            )
            folder = (
                pathlib.PurePosixPath("submissions")
                / _component(problem, "problem key")
                / _component(team, "team name")
                / f"{int(submission.submission_time):d}_{identifier}"
            )
            names = _file_names(submission)
            (root / folder).mkdir(parents=True)
            for name, file in zip(names, submission.files, strict=True):
                (root / folder / name).write_bytes(file.content)
            records.append(
                SubmissionRecord(
                    id=identifier,
                    folder=str(folder),
                    files=names,
                    language=submission.language_key,
                    time=submission.submission_time,
                    timing=deadlines.timing(submission.submission_time, extension),
                    verdict=submission.verdict,
                    solved_samples=_solved_samples(submission),
                    solved=submission.verdict == Verdict.CORRECT,
                    source=submission.is_source_submission,
                )
            )
        counting = select(records)
        teams[team].problems[problem] = TeamProblem(
            submissions=records, counting=counting.id if counting else None
        )
        if counting is None:
            continue
        source, final = root / counting.folder, root / "final" / team
        if flatten_single_file and len(counting.files) == 1:
            (name,) = counting.files
            _copy(
                source / name, final / f"{problem}{pathlib.PurePosixPath(name).suffix}"
            )
        else:
            for name in counting.files:
                _copy(source / name, final / problem / name)
    for part in OWNED:
        (root / part).mkdir(exist_ok=True)
    return teams


def build_layout(
    export: ContestDataExport,
    directory: pathlib.Path,
    *,
    deadlines: Deadlines,
    extensions: Mapping[str, datetime.timedelta] | None = None,
    select: Selection = last_before_cutoff,
    flatten_single_file: bool = False,
    export_mtime: float | None = None,
) -> Evaluation:
    """The layout of an export below directory, see the module docstring.

    Extensions are keyed by team key (the team's external id, else its name);
    ``Roster.resolve_teams`` turns extensions keyed by student ID or email into
    these. Without export_mtime, nothing is cached.
    """
    extensions = dict(extensions or {})
    config = _fingerprint(deadlines, extensions, select, flatten_single_file)
    if (cached := _cached(directory, export_mtime, config)) is not None:
        log.debug("Grading layout in %s is up to date", directory)
        return cached

    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".layout-", dir=directory) as temporary:
        root = pathlib.Path(temporary)
        teams = _build(
            export,
            root,
            deadlines=deadlines,
            extensions=extensions,
            select=select,
            flatten_single_file=flatten_single_file,
        )
        evaluation = Evaluation(
            contest_key=export.description.contest_key,
            export_mtime=export_mtime,
            config=config,
            teams=teams,
        )
        # The evaluation goes last, so an interrupted rebuild is not taken for
        # a complete one
        (directory / EVALUATION_FILE).unlink(missing_ok=True)
        for part in OWNED:
            old = directory / part
            if old.exists():
                shutil.rmtree(old)
            os.replace(root / part, old)
        (root / EVALUATION_FILE).write_text(evaluation.model_dump_json())
        os.replace(root / EVALUATION_FILE, directory / EVALUATION_FILE)

    counts = defaultdict(int)
    for record in teams.values():
        for entry in record.problems.values():
            for submission in entry.submissions:
                counts[submission.timing] += 1
    log.info(
        "Grading layout: %d submissions on time, %d late, %d too late",
        counts["on_time"],
        counts["late"],
        counts["too_late"],
    )
    return evaluation


def layout_export(
    export_path: pathlib.Path,
    directory: pathlib.Path,
    *,
    deadlines: Deadlines,
    extensions: Mapping[str, datetime.timedelta] | None = None,
    select: Selection = last_before_cutoff,
    flatten_single_file: bool = False,
) -> Evaluation:
    """build_layout for an export file (JSON, or .gz), cached by its
    modification time: the file is only read when the layout is out of date."""
    export_mtime = export_path.stat().st_mtime
    config = _fingerprint(
        deadlines, dict(extensions or {}), select, flatten_single_file
    )
    if (cached := _cached(directory, export_mtime, config)) is not None:
        log.debug("Grading layout in %s is up to date", directory)
        return cached
    export = ContestDataExport.model_validate_json(read_str_from(export_path))
    return build_layout(
        export,
        directory,
        deadlines=deadlines,
        extensions=extensions,
        select=select,
        flatten_single_file=flatten_single_file,
        export_mtime=export_mtime,
    )
