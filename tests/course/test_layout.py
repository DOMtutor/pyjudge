"""The grading layout, on synthetic exports."""

import datetime
import gzip
import json
import os
import pathlib
from collections.abc import Sequence

import pytest

from pydomjudge.database import (
    ContestDataExport,
    ContestDescriptionDto,
    SubmissionDto,
    SubmissionFileDto,
    TeamDto,
    TestcaseResultDto as CaseResult,
)
from pydomjudge.model import Verdict
from pydomjudge_course.layout import (
    Deadlines,
    Evaluation,
    SubmissionRecord,
    build_layout,
    last_before_cutoff,
    layout_export,
    load_evaluation,
)
from pydomjudge_course.roster import IdentityConfig, Person, Roster

END = datetime.datetime(2026, 3, 1, 12, 0, tzinfo=datetime.UTC)
MINUTE = datetime.timedelta(minutes=1)
DAY = datetime.timedelta(days=1)
DEADLINES = Deadlines(END, grace=10 * MINUTE, late=DAY)
BINARY = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"


def _at(offset: datetime.timedelta) -> float:
    return (END + offset).timestamp()


def _team(name: str, category: str | None = "participants") -> TeamDto:
    return TeamDto(
        name=name,
        display_name=name.upper(),
        category_name=category,
        affiliation_name=None,
        external_id=name,
        member_login_names=[f"{name}_login"],
    )


def _submission(
    team: str,
    offset: datetime.timedelta,
    *,
    problem: str = "A",
    verdict: Verdict | None = Verdict.CORRECT,
    samples: Sequence[Verdict] = (Verdict.CORRECT,),
    files: dict[str, bytes] | None = None,
    language: str = "python",
    external_id: str | None = None,
) -> SubmissionDto:
    return SubmissionDto(
        team_name=team,
        contest_key="exercise",
        contest_problem_key=problem,
        problem_name=problem.lower(),
        language_key=language,
        submission_time=_at(offset),
        external_id=external_id,
        verdict=verdict,
        case_result=[
            CaseResult(runtime=0.1, verdict=v, is_sample=True, test_name=f"sample{i}")
            for i, v in enumerate(samples)
        ]
        + [
            CaseResult(
                runtime=0.1,
                verdict=verdict or Verdict.CORRECT,
                is_sample=False,
                test_name="secret",
            )
        ],
        too_late=False,
        files=[
            SubmissionFileDto(filename=name, content=content)
            for name, content in (files or {"main.py": b"print(1)\n"}).items()
        ],
    )


def _export(
    *submissions: SubmissionDto, teams: Sequence[TeamDto] = ()
) -> ContestDataExport:
    teams = list(teams) or [_team("alice"), _team("bob")]
    return ContestDataExport(
        description=ContestDescriptionDto(
            contest_key="exercise", start=_at(-7 * DAY), end=END.timestamp()
        ),
        users={},
        teams={team.name: team for team in teams},
        languages={"python": "Python 3", "c": "C"},
        problems={"A": "adding", "B": "bacteria"},
        submissions=list(submissions),
        clarifications=[],
    )


def _files(directory: pathlib.Path) -> set[str]:
    return {
        str(path.relative_to(directory))
        for path in directory.rglob("*")
        if path.is_file()
    }


def _counting(
    evaluation: Evaluation, team: str, problem: str = "adding"
) -> SubmissionRecord:
    submission = evaluation.counting(team, problem)
    assert submission is not None
    return submission


def test_layout_keeps_every_submission_with_its_file_names(tmp_path: pathlib.Path):
    export = _export(
        _submission("alice", -DAY, files={"adding.py": b"a\n"}),
        _submission(
            "alice",
            -MINUTE,
            files={"main.c": b"int main;\n", "util.h": b"\n"},
            language="c",
            external_id="s42",
        ),
        _submission("alice", 2 * DAY, files={"late.py": b"too late\n"}),
        _submission("bob", -DAY, problem="B", files={"picture.png": BINARY}),
    )
    evaluation = build_layout(export, tmp_path, deadlines=DEADLINES)

    first, second = int(_at(-DAY)), int(_at(-MINUTE))
    assert _files(tmp_path / "submissions") == {
        f"adding/alice/{first}_n1/adding.py",
        f"adding/alice/{second}_s42/main.c",
        f"adding/alice/{second}_s42/util.h",
        f"adding/alice/{int(_at(2 * DAY))}_n3/late.py",
        f"bacteria/bob/{first}_n1/picture.png",
    }
    # the counting submission: the last one before the cutoff, a folder as it
    # has two files
    assert _files(tmp_path / "final") == {
        "alice/adding/main.c",
        "alice/adding/util.h",
        "bob/bacteria/picture.png",
    }
    assert (tmp_path / "final/bob/bacteria/picture.png").read_bytes() == BINARY

    alice = evaluation.teams["alice"]
    assert alice.members == ["alice_login"] and alice.category == "participants"
    records = alice.problems["adding"].submissions
    assert [r.id for r in records] == ["n1", "s42", "n3"]
    assert [r.timing for r in records] == ["on_time", "on_time", "too_late"]
    assert records[1].files == ["main.c", "util.h"] and records[1].language == "c"
    assert records[1].folder == f"submissions/adding/alice/{second}_s42"
    assert evaluation.counting("alice", "adding") == records[1]
    (bob,) = evaluation.teams["bob"].problems["bacteria"].submissions
    assert not bob.source and records[0].source
    assert evaluation.counting("bob", "adding") is None
    assert evaluation.counting("nobody", "adding") is None


@pytest.mark.parametrize(
    ("offset", "timing"),
    [
        (datetime.timedelta(0), "on_time"),
        (10 * MINUTE, "on_time"),
        (10 * MINUTE + datetime.timedelta(seconds=1), "late"),
        (DAY, "late"),
        (DAY + datetime.timedelta(seconds=1), "too_late"),
    ],
)
def test_timing_at_the_boundaries(offset, timing):
    assert DEADLINES.timing(_at(offset)) == timing
    # an extension moves the end
    assert DEADLINES.timing(_at(offset + DAY), extension=DAY) == timing


def test_deadlines_need_a_time_zone_and_ordered_windows():
    with pytest.raises(ValueError, match="time zone"):
        Deadlines(END.replace(tzinfo=None))
    with pytest.raises(ValueError, match="grace <= late"):
        Deadlines(END, grace=DAY, late=MINUTE)


def test_extension_by_student_id_keeps_submissions_after_the_late_window(
    tmp_path: pathlib.Path,
):
    # Extensions in grading.yaml are keyed by student ID; the export knows
    # teams. An extension longer than the late window must still count.
    roster = Roster.open(tmp_path / "roster.csv", IdentityConfig())
    roster.add(
        [
            Person(
                identity={"student_id": "9000001"}, first_name="A", last_name="B", row=1
            ),
            Person(
                identity={"student_id": "9000002"}, first_name="C", last_name="D", row=2
            ),
        ],
        display_name=lambda person, _id: person.first_name,
    )
    extended, other = (
        roster.by_login("9000001").team_key,
        roster.by_login("9000002").team_key,
    )
    export = _export(
        _submission(extended, 3 * DAY),
        _submission(extended, 3 * DAY + 30 * MINUTE),
        _submission(other, 3 * DAY),
        teams=[_team(extended), _team(other)],
    )
    extensions = roster.resolve_teams({"9000001": 3 * DAY})
    evaluation = build_layout(
        export, tmp_path / "layout", deadlines=DEADLINES, extensions=extensions
    )
    timings = [
        s.timing for s in evaluation.teams[extended].problems["adding"].submissions
    ]
    assert timings == ["on_time", "late"]
    assert _counting(evaluation, extended, "adding").timing == "late"
    assert evaluation.counting(other, "adding") is None


def test_a_late_resubmission_replaces_an_on_time_one(tmp_path: pathlib.Path):
    export = _export(
        _submission("alice", -DAY, external_id="first"),
        _submission(
            "alice",
            2 * MINUTE + 10 * MINUTE,
            verdict=Verdict.WRONG_ANSWER,
            external_id="second",
        ),
    )
    evaluation = build_layout(export, tmp_path, deadlines=DEADLINES)
    counting = _counting(evaluation, "alice")
    assert counting.id == "second"
    assert counting.timing == "late" and not counting.solved


def last_on_time(submissions: Sequence[SubmissionRecord]) -> SubmissionRecord | None:
    on_time = [s for s in submissions if s.timing == "on_time"]
    return on_time[-1] if on_time else last_before_cutoff(submissions)


def test_custom_rule(tmp_path: pathlib.Path):
    export = _export(
        _submission("alice", -DAY, external_id="first"),
        _submission("alice", 12 * MINUTE, external_id="second"),
    )
    evaluation = build_layout(
        export, tmp_path, deadlines=DEADLINES, select=last_on_time
    )
    assert _counting(evaluation, "alice", "adding").id == "first"


def test_graded_are_the_counting_ones_that_solve_the_samples(tmp_path: pathlib.Path):
    export = _export(
        _submission("alice", -DAY),
        _submission("alice", -DAY, problem="B", verdict=Verdict.WRONG_ANSWER),
        _submission(
            "bob",
            -DAY,
            verdict=Verdict.WRONG_ANSWER,
            samples=(Verdict.CORRECT, Verdict.WRONG_ANSWER),
        ),
        # judged without results: no samples solved
        SubmissionDto.model_validate(
            {**_submission("bob", -MINUTE, problem="B").model_dump(), "case_result": []}
        ),
    )
    evaluation = build_layout(export, tmp_path, deadlines=DEADLINES)
    graded = [(team, problem, s.solved) for team, problem, s in evaluation.graded()]
    assert graded == [("alice", "adding", True), ("alice", "bacteria", False)]


def test_cache_by_export_time_and_configuration(tmp_path: pathlib.Path):
    export = _export(_submission("alice", 2 * DAY))
    build_layout(export, tmp_path, deadlines=DEADLINES, export_mtime=1.0)
    stamp = (tmp_path / "evaluation.json").stat().st_mtime_ns
    marker = tmp_path / "submissions" / "marker"
    marker.write_text("")

    # unchanged: loaded, nothing written
    evaluation = build_layout(export, tmp_path, deadlines=DEADLINES, export_mtime=1.0)
    assert (tmp_path / "evaluation.json").stat().st_mtime_ns == stamp
    assert marker.exists() and evaluation.counting("alice", "adding") is None

    # a changed extension rebuilds, and the layout owns submissions/
    evaluation = build_layout(
        export,
        tmp_path,
        deadlines=DEADLINES,
        export_mtime=1.0,
        extensions={"alice": DAY},
    )
    assert not marker.exists()
    assert _counting(evaluation, "alice", "adding").timing == "late"
    # as do a changed deadline and a newer export
    later = Deadlines(END + 3 * DAY)
    evaluation = build_layout(export, tmp_path, deadlines=later, export_mtime=1.0)
    assert _counting(evaluation, "alice").timing == "on_time"
    marker.write_text("")
    build_layout(export, tmp_path, deadlines=later, export_mtime=2.0)
    assert not marker.exists()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".layout-")]


def test_layout_export_reads_the_file_only_when_out_of_date(tmp_path: pathlib.Path):
    export_path = tmp_path / "export.json.gz"
    with gzip.open(export_path, "wt") as f:
        f.write(_export(_submission("alice", -DAY)).model_dump_json())
    layout = tmp_path / "data"
    first = layout_export(export_path, layout, deadlines=DEADLINES)
    assert first.export_mtime == export_path.stat().st_mtime
    mtime = export_path.stat().st_mtime
    export_path.write_bytes(gzip.compress(b"not json"))
    os.utime(export_path, (mtime, mtime))
    assert layout_export(export_path, layout, deadlines=DEADLINES) == first


def test_flatten_single_file(tmp_path: pathlib.Path):
    export = _export(
        _submission(
            "alice",
            -DAY,
            files={"Solution.java": b"class Solution {}\n"},
            language="java",
        ),
        _submission("bob", -DAY, files={"a.c": b"\n", "b.h": b"\n"}, language="c"),
    )
    build_layout(export, tmp_path, deadlines=DEADLINES, flatten_single_file=True)
    assert _files(tmp_path / "final") == {
        "alice/adding.java",
        "bob/adding/a.c",
        "bob/adding/b.h",
    }


def test_hidden_teams_and_teams_without_submissions(tmp_path: pathlib.Path):
    export = _export(
        _submission("hidden", -DAY),
        teams=[_team("hidden", category="hidden-students"), _team("idle")],
    )
    evaluation = build_layout(export, tmp_path, deadlines=DEADLINES)
    assert evaluation.counting("hidden", "adding") is not None
    assert evaluation.teams["idle"].problems == {}


def test_unsafe_names(tmp_path: pathlib.Path):
    export = _export(
        _submission("alice", -DAY, files={"../escape.py": b"\n", "dir\\x.py": b"\n"}),
    )
    evaluation = build_layout(export, tmp_path, deadlines=DEADLINES)
    assert _counting(evaluation, "alice", "adding").files == ["escape.py", "x.py"]
    with pytest.raises(ValueError, match="folder name"):
        build_layout(
            _export(_submission("../x", -DAY), teams=[_team("../x")]),
            tmp_path / "other",
            deadlines=DEADLINES,
        )


def test_evaluation_round_trip(tmp_path: pathlib.Path):
    export = _export(
        _submission("alice", -DAY, verdict=None, samples=()),
        _submission("bob", 12 * MINUTE, verdict=Verdict.TIME_LIMIT),
    )
    evaluation = build_layout(export, tmp_path, deadlines=DEADLINES, export_mtime=3.0)
    assert load_evaluation(tmp_path) == evaluation
    stored = json.loads((tmp_path / "evaluation.json").read_text())
    record = stored["teams"]["bob"]["problems"]["adding"]["submissions"][0]
    assert record["verdict"] == "timelimit" and record["timing"] == "late"
    assert _counting(Evaluation.model_validate(stored), "alice").verdict is None
