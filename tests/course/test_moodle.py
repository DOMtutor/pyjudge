"""Moodle views, on synthetic files with the headers observed in the exports
of an English Moodle site (2026-10)."""

import json
import pathlib
from collections.abc import Sequence

import openpyxl
import pytest

from pydomjudge_course.moodle import (
    Gradebook,
    MoodleFormatError,
    Worksheet,
    identities,
    read_choice_responses,
    read_participants,
    send_feedback,
    send_login_data,
)
from pydomjudge_course.tables import Table, read_table, write_table

WORKSHEET_HEADER = [
    "Identifier",
    "First name",
    "Last name",
    "Username",
    "Student ID",
    "Email address",
    "Status",
    "Grade (Coursework Feedback)",
    "Maximum grade",
    "Grade can be changed",
    "Last modified (grade)",
    "Feedback comments",
]
CHOICE_HEADER = [
    "Last name",
    "First name",
    "Username",
    "Student ID",
    "Email address",
    "Group",
    "Choice",
]


def _worksheet_rows() -> list[list[object]]:
    return [
        ["Participant 101", "Alice", "Example", "alice1", 9000001, "alice@example.org",
         "No submission", None, 100, "Yes", None, None],
        ["Participant 102", "Bob", "Example", "bob2", "9000002|9000012", "Bob@Example.org",
         "No submission", None, 100, "Yes", None, None],
        ["Participant 103", "Carol", "Example", "carol3", 9000003, "carol@example.org",
         "No submission", None, 100, "Yes", None, None],
    ]  # fmt: skip


def _xlsx(
    path: pathlib.Path, header: list[str], rows: Sequence[Sequence[object]]
) -> pathlib.Path:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


@pytest.fixture
def worksheet_path(tmp_path: pathlib.Path) -> pathlib.Path:
    return _xlsx(tmp_path / "worksheet.xlsx", WORKSHEET_HEADER, _worksheet_rows())


def test_identities():
    assert identities(" 9000002|9000012 ") == ("9000002", "9000012")
    assert identities("Bob@Example.org") == ("bob@example.org",)
    assert identities("") == () and identities(None) == ()


def test_read_worksheet(worksheet_path: pathlib.Path):
    worksheet = Worksheet.read(worksheet_path)
    assert worksheet.grade == "Grade (Coursework Feedback)"
    assert worksheet.feedback == "Feedback comments"
    assert worksheet.identity == {
        "email": "Email address",
        "student_id": "Student ID",
        "username": "Username",
    }
    first = worksheet.rows[0]
    assert worksheet.participant_id(first) == "101"
    assert worksheet.full_name(first) == "Alice Example"
    by_id = worksheet.rows_by("student_id")
    assert by_id["9000012"] is by_id["9000002"] is worksheet.rows[1]
    assert worksheet.rows_by("email")["bob@example.org"] is worksheet.rows[1]


def test_worksheet_with_full_name_and_exact_grade(tmp_path: pathlib.Path):
    path = tmp_path / "default.csv"
    path.write_text(
        "Identifier,Full name,Email address,Status,Grade,Maximum grade,"
        "Grade can be changed,Feedback comments\n"
        "Participant 7,Dana Example,dana@example.org,,,100,Yes,\n"
    )
    worksheet = Worksheet.read(path)
    assert worksheet.grade == "Grade"
    assert worksheet.identity == {"email": "Email address"}
    assert worksheet.full_name(worksheet.rows[0]) == "Dana Example"


@pytest.mark.parametrize(
    ("header", "row", "message"),
    [
        (["Full name", "Grade", "Feedback comments"], ["x", "", ""], "no 'Identifier'"),
        (["Identifier", "Grade", "Feedback comments"], ["Someone", "", ""], "data row 1"),
        (["Identifier", "Grade (A)", "Grade (B)", "Feedback comments"],
         ["Participant 1", "", "", ""], "expected one 'Grade' column"),
        (["Identifier", "Grade can be changed", "Feedback comments"],
         ["Participant 1", "", ""], "found none"),
        (["Identifier", "Grade", "Status"], ["Participant 1", "", ""], "'Feedback'"),
    ],
)  # fmt: skip
def test_worksheet_errors(tmp_path: pathlib.Path, header, row, message):
    path = tmp_path / "bad.csv"
    write_table(
        Table(header=tuple(header), rows=[dict(zip(header, row, strict=True))]), path
    )
    with pytest.raises(MoodleFormatError, match=message):
        Worksheet.read(path)


def test_duplicate_identity(tmp_path: pathlib.Path):
    rows = _worksheet_rows()
    rows[2][5] = "ALICE@example.org"
    worksheet = Worksheet.read(_xlsx(tmp_path / "dup.xlsx", WORKSHEET_HEADER, rows))
    with pytest.raises(
        MoodleFormatError, match="data rows 1 and 3 have the same Email"
    ) as error:
        worksheet.rows_by("email")
    assert "alice" not in str(error.value).casefold()


def test_fill_by_student_id(worksheet_path: pathlib.Path):
    worksheet = Worksheet.read(worksheet_path)
    report = worksheet.target.fill(
        {
            "9000001": ("80.00", "<p>A</p>"),
            "9000012": ("70.00", "<p>B</p>"),
            "9999999": ("1", "x"),
        },
        by="student_id",
    )
    assert report.filled == 2
    assert report.unmatched_keys == ["9999999"]
    assert report.unfilled_rows == [3]
    assert worksheet.rows[1]["Grade (Coursework Feedback)"] == "70.00"
    assert worksheet.rows[1]["Feedback comments"] == "<p>B</p>"
    assert worksheet.rows[2]["Feedback comments"] == ""
    with pytest.raises(MoodleFormatError, match="no value for data rows 2, 3"):
        worksheet.target.fill({"9000001": ("1", "x")}, by="student_id", missing="error")
    with pytest.raises(MoodleFormatError, match="no student_id column"):
        Worksheet.read(_csv_without_ids(worksheet_path.parent)).target.fill(
            {}, by="student_id"
        )


def _csv_without_ids(directory: pathlib.Path) -> pathlib.Path:
    path = directory / "plain.csv"
    path.write_text("Identifier,Grade,Feedback comments\nParticipant 1,,\n")
    return path


def test_fill_error_changes_nothing(worksheet_path: pathlib.Path):
    worksheet = Worksheet.read(worksheet_path)
    with pytest.raises(MoodleFormatError, match="no value for data rows 2, 3"):
        worksheet.target.fill(
            {"alice@example.org": ("1", "x")}, by="email", missing="error"
        )
    assert worksheet.rows[0]["Feedback comments"] == ""


def test_write_keeps_header_and_identifiers(worksheet_path: pathlib.Path, tmp_path):
    worksheet = Worksheet.read(worksheet_path)
    send_login_data(
        worksheet.target, {"alice1": ("alice1", "AppleBananaCherry")}, by="username"
    )
    target = tmp_path / "upload.csv"
    worksheet.write(target)
    again = read_table(target)
    assert again.header == tuple(WORKSHEET_HEADER)
    assert [row["Identifier"] for row in again.rows] == [
        "Participant 101",
        "Participant 102",
        "Participant 103",
    ]
    assert again.rows[0]["Student ID"] == "9000001"
    assert again.rows[0]["Grade (Coursework Feedback)"] == "1"
    assert again.rows[0]["Feedback comments"] == (
        "Your login name: alice1\nYour password: AppleBananaCherry"
    )
    with pytest.raises(NotImplementedError):
        worksheet.write(tmp_path / "upload.xlsx")


def test_send_feedback(worksheet_path: pathlib.Path):
    worksheet = Worksheet.read(worksheet_path)
    results = {
        "alice@example.org": (87.5, "<p>a</p>"),
        "bob@example.org": ("n/a", "<p>b</p>"),
    }
    with pytest.raises(MoodleFormatError, match="no value for data rows 3"):
        send_feedback(worksheet.target, results, by="email")
    report = send_feedback(worksheet.target, results, by="email", missing="keep")
    assert report.unfilled_rows == [3]
    assert worksheet.rows[0]["Grade (Coursework Feedback)"] == "87.50"
    assert worksheet.rows[1]["Grade (Coursework Feedback)"] == "n/a"


def test_send_login_data_keeps_rows_without_credentials(worksheet_path: pathlib.Path):
    worksheet = Worksheet.read(worksheet_path)
    report = send_login_data(
        worksheet.target,
        {"9000003": ("carol3", "pw"), "9000099": ("late", "pw")},
        by="student_id",
    )
    assert (report.filled, report.unmatched_keys, report.unfilled_rows) == (
        1,
        ["9000099"],
        [1, 2],
    )
    assert worksheet.rows[2]["Grade (Coursework Feedback)"] == "1"


def test_read_participants(tmp_path: pathlib.Path):
    path = tmp_path / "participants.json"
    path.write_text(
        json.dumps(
            [
                [
                    {"firstname": "Alice", "lastname": "EXAMPLE", "email": "alice@example.org",
                     "studentid": "9000001"},
                    {"firstname": "Bob", "lastname": "EXAMPLE", "emailaddress": "bob@example.org",
                     "studentid": "9000002|9000012"},
                    {"firstname": "Staff", "lastname": "Member", "email": "staff@example.org",
                     "studentid": ""},
                ]
            ]
        )
    )  # fmt: skip
    participants = read_participants(path)
    assert [p.identity for p in participants] == [
        {"email": "alice@example.org", "student_id": "9000001"},
        {"email": "bob@example.org", "student_id": "9000002|9000012"},
        {"email": "staff@example.org"},
    ]
    assert (participants[0].first_name, participants[0].last_name) == (
        "Alice",
        "EXAMPLE",
    )

    path.write_text(json.dumps({"not": "a list"}))
    with pytest.raises(MoodleFormatError, match="list of participant records"):
        read_participants(path)


@pytest.mark.parametrize("suffix", [".txt", ".xlsx"])
def test_read_choice_responses(tmp_path: pathlib.Path, suffix):
    rows = [
        ["Example", "Alice", "alice1", "9000001", "alice@example.org", "", "Hidden"],
        ["Member", "Staff", "staff", "", "staff@example.org", "", ""],
    ]
    path = tmp_path / f"visibility{suffix}"
    if suffix == ".xlsx":
        _xlsx(path, CHOICE_HEADER, rows)
    else:
        path.write_text(
            "\n".join("\t".join(row) for row in [CHOICE_HEADER, *rows]) + "\n"
        )
    responses = read_choice_responses(path)
    assert responses[0].identity == {
        "email": "alice@example.org",
        "student_id": "9000001",
        "username": "alice1",
    }
    assert responses[0].choice == "Hidden"
    assert responses[0].name == "Alice Example"
    assert responses[1].identity == {"email": "staff@example.org", "username": "staff"}
    assert responses[1].choice == ""


def test_choice_without_choice_column(tmp_path: pathlib.Path):
    path = tmp_path / "x.txt"
    path.write_text("Email address\tGroup\na@example.org\t\n")
    with pytest.raises(MoodleFormatError, match="no 'Choice' column"):
        read_choice_responses(path)


# The gradebook header observed in a "Grades.xlsx" export
GRADEBOOK_HEADER = [
    "First name",
    "Last name",
    "Student ID",
    "Institution",
    "Department",
    "Email address",
    "Assignment: Judge Password (Real)",
    "Assignment: Judge Password (Feedback)",
    "Last downloaded from this course",
]
# Made up, not observed: a course total, and an export without feedback
GRADEBOOK_WITH_TOTAL = [
    *GRADEBOOK_HEADER[:8],
    "Course total (Real)",
    GRADEBOOK_HEADER[8],
]
GRADEBOOK_WITHOUT_FEEDBACK = [
    name for name in GRADEBOOK_HEADER if not name.endswith("(Feedback)")
]


def _gradebook(tmp_path: pathlib.Path, header: list[str]) -> Gradebook:
    rows = []
    for number, (first, mail) in enumerate(
        [("Alice", "alice@example.org"), ("Bob", "bob@example.org")], start=1
    ):
        values = {
            "First name": first,
            "Last name": "Example",
            "Student ID": f"900000{number}",
            "Email address": mail,
            "Last downloaded from this course": "1 January 2030",
            "Course total (Real)": "12.00",
        }
        rows.append([values.get(name, "") for name in header])
    return Gradebook.read(_xlsx(tmp_path / "grades.xlsx", header, rows))


def test_gradebook_items_and_target(tmp_path: pathlib.Path):
    gradebook = _gradebook(tmp_path, GRADEBOOK_HEADER)
    assert gradebook.identity == {"email": "Email address", "student_id": "Student ID"}
    (item,) = gradebook.items()
    assert (item.type, item.name) == ("Assignment", "Judge Password")
    target = gradebook.target("Judge Password")
    assert gradebook.target("Assignment: Judge Password") == target
    assert (target.grade, target.feedback) == (
        "Assignment: Judge Password (Real)",
        "Assignment: Judge Password (Feedback)",
    )
    with pytest.raises(MoodleFormatError, match="no grade item 'Quiz'.*Judge Password"):
        gradebook.target("Quiz")


def test_gradebook_login_data_keeps_other_columns(tmp_path: pathlib.Path):
    gradebook = _gradebook(tmp_path, GRADEBOOK_WITH_TOTAL)
    assert [item.name for item in gradebook.items()] == ["Judge Password"]
    report = send_login_data(
        gradebook.target("Judge Password"),
        {"9000001": ("alice1", "pw")},
        by="student_id",
    )
    assert report.filled == 1 and report.unfilled_rows == [2]
    target = tmp_path / "upload.csv"
    gradebook.write(target)
    again = read_table(target)
    assert again.header == tuple(GRADEBOOK_WITH_TOTAL)
    assert again.rows[0]["Assignment: Judge Password (Real)"] == "1"
    assert again.rows[0]["Assignment: Judge Password (Feedback)"].startswith(
        "Your login name: alice1"
    )
    assert again.rows[0]["Course total (Real)"] == "12.00"
    assert again.rows[1]["Last downloaded from this course"] == "1 January 2030"


def test_gradebook_without_feedback_column(tmp_path: pathlib.Path):
    gradebook = _gradebook(tmp_path, GRADEBOOK_WITHOUT_FEEDBACK)
    target = gradebook.target("Judge Password")
    assert target.feedback is None
    with pytest.raises(MoodleFormatError, match="no feedback column"):
        send_login_data(target, {"9000001": ("a", "pw")}, by="student_id")
    send_feedback(target, {"9000001": (5, None), "9000002": (6, None)}, by="student_id")
    assert [row["Assignment: Judge Password (Real)"] for row in gradebook.rows] == [
        "5.00",
        "6.00",
    ]


def test_gradebook_item_without_real_column(tmp_path: pathlib.Path):
    header = ["Email address", "Quiz: Week 1 (Percentage)", "Quiz: Week 1 (Feedback)"]
    gradebook = Gradebook.read(
        _xlsx(tmp_path / "pct.xlsx", header, [["a@example.org", "", ""]])
    )
    with pytest.raises(MoodleFormatError, match=r"no \(Real\) column, only Quiz"):
        gradebook.target("Week 1")
    with pytest.raises(MoodleFormatError, match="no identity column"):
        Gradebook.read(_xlsx(tmp_path / "none.xlsx", ["Quiz: A (Real)"], [["1"]]))
