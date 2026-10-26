"""Plagiarism candidates, review files and verdicts, on synthetic programs."""

import csv
import datetime
import pathlib
import random

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
from pydomjudge_course.layout import Deadlines, build_layout
from pydomjudge_course.plagiarism import (
    CommentDetector,
    PairScore,
    ReviewError,
    TeamPair,
    Unit,
    find_cases,
    find_plagiarism,
    findings,
    hearings,
    read_reviews,
    units_from_layout,
    update_review,
    write_evidence,
    write_findings,
)

END = datetime.datetime(2026, 3, 1, 12, 0, tzinfo=datetime.UTC)
DAY = datetime.timedelta(days=1)
WORDS = ["count", "total", "value", "item", "index", "result", "limit", "node"]


def _part(seed: int, lines: int = 40) -> list[str]:
    """Lines of C that only this seed produces."""
    rng = random.Random(seed)
    body = []
    for i in range(lines):
        a, b = rng.choice(WORDS), rng.choice(WORDS)
        body.append(
            f"    int {a}{seed}_{i} = {b}{rng.randint(0, 9)} * {rng.randint(1, 99)}"
            f" + {rng.randint(100, 999)};"
        )
        if i % 6 == 0:
            body.append(f'    if ({a}{seed}_{i} > {rng.randint(10, 99)}) puts("x");')
    return body


def _program(*parts: list[str]) -> bytes:
    lines = ["#include <stdio.h>", "int main(void) {"]
    for part in parts:
        lines.extend(part)
    lines += ["    return 0;", "}", ""]
    return "\n".join(lines).encode()


def _layout(tmp_path: pathlib.Path, programs: dict[str, list[tuple[float, bytes]]]):
    """A layout of problem "adding" with the given (day offset, source) per team."""
    submissions = [
        SubmissionDto(
            team_name=team,
            contest_key="ex",
            contest_problem_key="A",
            problem_name="adding",
            language_key="c",
            submission_time=(END + offset * DAY).timestamp(),
            verdict=Verdict.CORRECT,
            case_result=[
                CaseResult(
                    runtime=0.1, verdict=Verdict.CORRECT, is_sample=True, test_name="1"
                )
            ],
            too_late=False,
            files=[SubmissionFileDto(filename="main.c", content=content)],
        )
        for team, items in programs.items()
        for offset, content in items
    ]
    export = ContestDataExport(
        description=ContestDescriptionDto(contest_key="ex", start=None, end=None),
        users={},
        teams={
            team: TeamDto(
                name=team,
                display_name=team,
                category_name="participants",
                affiliation_name=None,
                member_login_names=[team],
            )
            for team in programs
        },
        languages={"c": "C"},
        problems={"A": "adding"},
        submissions=submissions,
        clarifications=[],
    )
    directory = tmp_path / "layout"
    evaluation = build_layout(export, directory, deadlines=Deadlines(END, late=DAY))
    return evaluation, directory


def _abcd(tmp_path: pathlib.Path):
    """A shares one part each with B, C and D, which share nothing."""
    one, two, three = _part(1), _part(2), _part(3)
    return _layout(
        tmp_path,
        {
            "A": [(-1, _program(one, two, three))],
            "B": [(-1, _program(one))],
            "C": [(-1, _program(two))],
            "D": [(-1, _program(three))],
            "E": [(-1, _program(_part(14), _part(15)))],
        },
    )


def _run(tmp_path: pathlib.Path, evaluation, layout, name: str = "report"):
    return find_plagiarism(
        evaluation,
        layout,
        report_directory=tmp_path / name,
        review_directory=tmp_path / "plagiarism",
    )


def _rows(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _set_verdicts(path: pathlib.Path, verdicts: dict[tuple[str, str], tuple[str, str]]):
    rows = _rows(path)
    for row in rows:
        if (row["a"], row["b"]) in verdicts:
            row["verdict_a"], row["verdict_b"] = verdicts[row["a"], row["b"]]
            row["review"] = ""
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_verdicts_per_pair_and_side(tmp_path: pathlib.Path):
    evaluation, layout = _abcd(tmp_path)
    pairs = _run(tmp_path, evaluation, layout)
    flagged = [(p.a, p.b) for p in pairs["adding"] if p.flagged]
    assert flagged == [("A", "B"), ("A", "C"), ("A", "D")]
    (case,) = find_cases(pairs["adding"])
    assert case.teams == ("A", "B", "C", "D")

    review = tmp_path / "plagiarism" / "adding.csv"
    rows = _rows(review)
    assert [(r["case"], r["a"], r["b"], r["review"]) for r in rows] == [
        ("C01", "A", "B", "new"),
        ("C01", "A", "C", "new"),
        ("C01", "A", "D", "new"),
    ]
    assert all(r["detectors"].startswith("code") for r in rows)
    with pytest.raises(ReviewError, match="review is 'new'"):
        read_reviews({"adding": review})

    # A copied from B; within A-C, A cited correctly but C did not; A-D is bogus
    _set_verdicts(
        review,
        {
            ("A", "B"): ("copied", "source"),
            ("A", "C"): ("cited", "uncited"),
            ("A", "D"): ("none", "none"),
        },
    )
    verdicts = read_reviews({"adding": review})
    team_hearings = hearings(verdicts)
    assert {
        team: [(h.problem, h.partner) for h in items]
        for team, items in team_hearings.items()
    } == {
        "A": [("adding", "B")],
        "C": [("adding", "A")],
    }
    assert team_hearings["C"][0].verdict == "uncited"
    assert team_hearings["C"][0].partner_verdict == "cited"
    results = findings(verdicts)
    assert [(f.team, f.verdict, f.partners) for f in results] == [
        ("A", "copied", ("B",)),
        ("C", "uncited", ("A",)),
    ]
    write_findings(results, tmp_path / "plagiarism.csv")
    assert _rows(tmp_path / "plagiarism.csv") == [
        {"team": "A", "problem": "adding", "verdict": "copied", "partners": "B"},
        {"team": "C", "problem": "adding", "verdict": "uncited", "partners": "A"},
    ]

    evidence = tmp_path / "evidence"
    write_evidence(team_hearings, tmp_path / "report", layout, evidence, evaluation)
    files = sorted(
        str(p.relative_to(evidence)) for p in evidence.rglob("*") if p.is_symlink()
    )
    stamp = int((END - DAY).timestamp())
    assert files == [
        f"A/adding/B/own/{stamp}_n1",
        f"A/adding/B/partner/{stamp}_n1",
        f"C/adding/A/own/{stamp}_n1",
        f"C/adding/A/partner/{stamp}_n1",
    ]
    assert (evidence / f"A/adding/B/partner/{stamp}_n1/main.c").is_file()


def test_rerun_keeps_verdicts(tmp_path: pathlib.Path):
    evaluation, layout = _abcd(tmp_path)
    _run(tmp_path, evaluation, layout)
    review = tmp_path / "plagiarism" / "adding.csv"
    _set_verdicts(review, {("A", "B"): ("copied", "source")})
    before = _rows(review)
    _run(tmp_path, evaluation, layout)
    assert _rows(review) == before
    assert before[0]["verdict_a"] == "copied" and before[0]["review"] == ""


def _unit(team: str, *submissions: str) -> Unit:
    return Unit(
        problem="adding",
        team=team,
        submissions=submissions,
        folders=tuple(f"submissions/adding/{team}/{s}" for s in submissions),
        files=("main.c",),
        language="c",
        time=0.0,
        sources=(),
    )


def _pair(a: Unit, b: Unit, score: float = 0.9) -> TeamPair:
    return TeamPair(
        "adding", a.team, b.team, (PairScore("code", a, b, score, 100, True),)
    )


def test_review_marks_new_dropped_and_changed_evidence(tmp_path: pathlib.Path):
    review = tmp_path / "adding.csv"
    ab, ac, ad = (
        _pair(_unit("A", "s1"), _unit("B", "s2")),
        _pair(_unit("A", "s1"), _unit("C", "s3")),
        _pair(_unit("A", "s1"), _unit("D", "s4")),
    )
    update_review(review, [ab, ac, ad])
    _set_verdicts(
        review, {("A", "B"): ("copied", "source"), ("A", "C"): ("none", "none")}
    )

    # A-B: other submissions; A-C: no longer flagged; A-D was never reviewed;
    # A-E is new
    update_review(
        review,
        [
            _pair(_unit("A", "s1"), _unit("B", "s2", "s5")),
            ad,
            _pair(_unit("A", "s1"), _unit("E", "s6")),
        ],
    )
    rows = {(r["a"], r["b"]): r for r in _rows(review)}
    assert {key: row["review"] for key, row in rows.items()} == {
        ("A", "B"): "re-review",
        ("A", "D"): "new",
        ("A", "E"): "new",
        ("A", "C"): "dropped",
    }
    assert rows["A", "B"]["verdict_a"] == "copied"
    assert rows["A", "C"]["case"] == "" and rows["A", "C"]["verdict_b"] == "none"
    # a different score bucket is a change, a small difference is not
    _set_verdicts(
        review,
        {
            key: (row["verdict_a"] or "none", row["verdict_b"] or "none")
            for key, row in rows.items()
        },
    )
    update_review(review, [_pair(_unit("A", "s1"), _unit("B", "s2", "s5"), 0.93)])
    assert _rows(review)[0]["review"] == ""
    update_review(review, [_pair(_unit("A", "s1"), _unit("B", "s2", "s5"), 0.75)])
    assert _rows(review)[0]["review"] == "re-review"
    # a dropped pair without verdict or note disappears
    update_review(tmp_path / "other.csv", [ab])
    update_review(tmp_path / "other.csv", [])
    assert _rows(tmp_path / "other.csv") == []


def test_course_kinds(tmp_path: pathlib.Path):
    # A course's own kinds: three reported levels, no "cited" or "source"
    kinds = {"none": 0, "minor": 1, "major": 2, "severe": 3}
    review = tmp_path / "adding.csv"
    update_review(
        review,
        [
            _pair(_unit("A", "s1"), _unit("B", "s2")),
            _pair(_unit("A", "s1"), _unit("C", "s3")),
        ],
    )
    _set_verdicts(
        review,
        {
            ("A", "B"): ("minor", "none"),
            ("A", "C"): ("severe", "major"),
        },
    )
    with pytest.raises(ReviewError, match="verdict_a must be one of none, cited"):
        read_reviews({"adding": review})
    verdicts = read_reviews({"adding": review}, kinds)
    assert [(f.team, f.verdict, f.partners) for f in findings(verdicts, kinds)] == [
        ("A", "severe", ("B", "C")),
        ("C", "major", ("A",)),
    ]
    assert [(h.team, h.partner) for h in hearings(verdicts, kinds)["A"]] == [
        ("A", "B"),
        ("A", "C"),
    ]
    with pytest.raises(ValueError, match="must not be negative"):
        read_reviews({"adding": review}, {**kinds, "none": -1})


def test_include_filter_and_collapsing(tmp_path: pathlib.Path):
    base = _part(1)
    evaluation, layout = _layout(
        tmp_path,
        {
            "A": [
                (-2, _program(base)),
                # a near-identical resubmission
                (-1, _program(base[:-1], ["    int changed = 1;"])),
                # too late, but before grading
                (3, _program(_part(2))),
            ],
            "B": [(-1, b"\xff\xfe\x00binary")],
        },
    )
    units = units_from_layout(evaluation, layout)["adding"]
    assert [(u.team, u.submissions) for u in units] == [
        ("A", ("n1", "n2")),
        ("A", ("n3",)),
    ]
    on_time = units_from_layout(
        evaluation, layout, include=lambda s: s.source and s.timing != "too_late"
    )["adding"]
    assert [u.submissions for u in on_time] == [("n1", "n2")]
    assert units_from_layout(evaluation, layout, collapse=1.0)["adding"][
        0
    ].submissions == ("n1",)


def test_comment_detector(tmp_path: pathlib.Path):
    comment = (
        "/* This program reads the numbers one by one and keeps a running total, "
        "printing the sum at the end because the task asks for it exactly so */"
    )
    a = Unit(
        "adding",
        "A",
        ("s1",),
        ("f",),
        ("main.c",),
        "c",
        0.0,
        (("main.c", comment + "\nint a;\n"),),
    )
    b = Unit(
        "adding",
        "B",
        ("s2",),
        ("f",),
        ("main.c",),
        "c",
        0.0,
        (("main.c", comment + "\nint b = 2;\n"),),
    )
    c = Unit(
        "adding",
        "C",
        ("s3",),
        ("f",),
        ("main.c",),
        "c",
        0.0,
        (("main.c", "/* short */ int c;\n"),),
    )
    detector = CommentDetector()
    (score,) = detector.detect([a, b, c], [], workspace=tmp_path)
    assert score.teams == ("A", "B") and score.flagged and score.score == 1.0
    assert detector.detect([a, b, c], [], skip={("A", "B")}, workspace=tmp_path) == []


def test_deterministic(tmp_path: pathlib.Path):
    evaluation, layout = _abcd(tmp_path)
    _run(tmp_path, evaluation, layout, "first")
    first_review = (tmp_path / "plagiarism" / "adding.csv").read_text()
    _run(tmp_path, evaluation, layout, "second")
    for name in ("adding/pairs.json", "index.html"):
        first = (tmp_path / "first" / name).read_text()
        assert first == (tmp_path / "second" / name).read_text()
    assert (tmp_path / "plagiarism" / "adding.csv").read_text() == first_review


def test_report_escapes_and_links(tmp_path: pathlib.Path):
    shared = _part(1)
    evaluation, layout = _layout(
        tmp_path,
        {
            "x<b>&": [(-1, _program(shared))],
            "y": [(-1, _program(shared, _part(6)))],
            "z": [(-1, _program(_part(7), _part(8)))],
        },
    )
    _run(tmp_path, evaluation, layout)
    index = (tmp_path / "report" / "index.html").read_text()
    assert "x&lt;b&gt;&amp;" in index and "x<b>" not in index
    assert "href='adding/code/report.html'" in index
    assert (tmp_path / "report" / "adding" / "code" / "report.html").is_file()
    assert "Team pairs on several problems" in index


def test_problems_without_units_drop_their_rows(tmp_path: pathlib.Path):
    evaluation, layout = _abcd(tmp_path)
    other = tmp_path / "plagiarism" / "bacteria.csv"
    update_review(other, [_pair(_unit("A", "s1"), _unit("B", "s2"))])
    _set_verdicts(other, {("A", "B"): ("copied", "source")})
    _run(tmp_path, evaluation, layout)
    (row,) = _rows(other)
    assert row["review"] == "dropped" and row["verdict_a"] == "copied"


def test_evidence_of_a_kept_dropped_pair(tmp_path: pathlib.Path, caplog):
    evaluation, layout = _abcd(tmp_path)
    _run(tmp_path, evaluation, layout)
    review = tmp_path / "plagiarism" / "adding.csv"
    # A-E is not flagged in this run, but a reviewer kept a verdict for it
    rows = _rows(review)
    rows.append({**rows[0], "case": "", "a": "A", "b": "E", "review": "dropped"})
    with review.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _set_verdicts(
        review,
        {
            ("A", "B"): ("none", "none"),
            ("A", "C"): ("none", "none"),
            ("A", "D"): ("none", "none"),
            ("A", "E"): ("source", "copied"),
        },
    )
    team_hearings = hearings(read_reviews({"adding": review}))
    assert list(team_hearings) == ["E"]
    evidence = tmp_path / "evidence"
    with caplog.at_level("WARNING"):
        write_evidence(team_hearings, tmp_path / "report", layout, evidence, evaluation)
    assert "adding: the pair A / E is not flagged" in caplog.text
    stamp = int((END - DAY).timestamp())
    assert sorted(
        str(p.relative_to(evidence)) for p in evidence.rglob("*") if p.is_symlink()
    ) == [f"E/adding/A/own/{stamp}_n1", f"E/adding/A/partner/{stamp}_n1"]
