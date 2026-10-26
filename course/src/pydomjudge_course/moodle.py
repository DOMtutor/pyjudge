"""Views of Moodle exports: grading worksheet, gradebook, participants, choice
responses.

Grades and feedback go back to Moodle on two paths, both sheets with the
identities of the participants (``MoodleSheet``): an assignment's grading
worksheet, which Moodle matches by its Identifier column, and the course
gradebook export, which Moodle matches by a user field chosen at import. Each
provides a ``FillTarget`` (grade column, feedback column), which
``send_login_data`` and ``send_feedback`` fill; ``write`` writes the sheet
with its columns unchanged.

Identities are matched, never guessed: a value can hold several identities
separated by ``|`` (one student enrolled twice), which ``identities`` splits
and normalises.
"""

import dataclasses
import json
import pathlib
import re
from collections.abc import Callable, Mapping
from typing import Literal

from .tables import Table, TableError, _decode as _decode_text, read_table

# Format assumptions, in one place. Observed in the exports of an English
# Moodle site (2026-10).
#
# Grading worksheet (xlsx), in this order: Identifier, First name, Last name,
# Username, Student ID, Email address, Status, Grade (<assignment name>),
# Maximum grade, Grade can be changed, Last modified (grade), Feedback comments
IDENTIFIER_COLUMN = "Identifier"
IDENTIFIER_PATTERN = re.compile(r"Participant (\d+)")
# The grade column is "Grade (<assignment name>)" or "Grade": the only column
# starting with this, apart from GRADE_EXCLUDED ("Maximum grade" does not)
GRADE_PREFIX = "Grade"
GRADE_EXCLUDED = ("Grade can be changed",)
FEEDBACK_COLUMN = "Feedback comments"
FEEDBACK_PREFIX = "Feedback"
# This site shows first and last name; "Full name" is Moodle's default
FIRST_NAME_COLUMN = "First name"
LAST_NAME_COLUMN = "Last name"
FULL_NAME_COLUMN = "Full name"
# Identity kind -> accepted column names. "ID number" is Moodle's default name
# of the student ID field, "Student ID" the observed one
IDENTITY_COLUMNS: dict[str, tuple[str, ...]] = {
    "email": ("Email address",),
    "student_id": ("Student ID", "ID number"),
    "username": ("Username",),
}
# Several identities in one value (a student enrolled twice)
IDENTITY_SEPARATOR = "|"
#
# Gradebook export ("Grades" > Export, xlsx): First name, Last name, Student
# ID, Institution, Department, Email address, "Assignment: <name> (Real)",
# "Assignment: <name> (Feedback)", Last downloaded from this course. Grade
# items are "<type>: <name> (<display>)"; the import takes the Real display,
# feedback only exists when exported with "include feedback"
GRADEBOOK_ITEM_PATTERN = re.compile(
    r"(?P<type>[^:()]+): (?P<name>.+) \((?P<display>[^()]+)\)"
)
GRADEBOOK_GRADE_DISPLAY = "Real"
GRADEBOOK_FEEDBACK_DISPLAY = "Feedback"
#
# Choice responses ("Download in text format": tab-separated .txt, utf-8
# without BOM; or xlsx with the same header): Last name, First name, Username,
# Student ID, Email address, Group, Choice. They also list staff.
CHOICE_COLUMN = "Choice"
#
# Participants ("Download table data as JSON" of the participants page), as
# course code reads it, not probed: a list whose first element is the
# list of records, with these keys
PARTICIPANT_KEYS: dict[str, tuple[str, ...]] = {
    "email": ("email", "emailaddress"),
    "student_id": ("studentid",),
    "username": ("username",),
}
PARTICIPANT_FIRST_NAME_KEY = "firstname"
PARTICIPANT_LAST_NAME_KEY = "lastname"
#
# What goes into the grade and feedback cells with the login data
LOGIN_TEXT = "Your login name: {login}\nYour password: {password}"
LOGIN_GRADE = "1"

IdentityKind = Literal["email", "student_id", "username"]
Missing = Literal["keep", "error"]


class MoodleFormatError(TableError):
    """An export that does not look as expected; the message names columns and
    row numbers, never values."""


def identities(value: str | None) -> tuple[str, ...]:
    """The identities in a value: split at "|", stripped, case-folded."""
    if not value:
        return ()
    parts = (part.strip().casefold() for part in value.split(IDENTITY_SEPARATOR))
    return tuple(part for part in parts if part)


def _identity_columns(table: Table) -> dict[str, str]:
    return {
        kind: column
        for kind, names in IDENTITY_COLUMNS.items()
        if (column := table.column(*names, required=False)) is not None
    }


def _single(table: Table, exact: str, prefix: str, excluded=()) -> str:
    if exact in table.header:
        return exact
    candidates = [
        name for name in table.columns_starting(prefix) if name not in excluded
    ]
    if len(candidates) != 1:
        found = ", ".join(map(repr, candidates)) if candidates else "none"
        raise MoodleFormatError(
            f"{table.source}: expected one {prefix!r} column, found {found}"
        )
    return candidates[0]


def _full_name(table: Table, row: dict[str, str]) -> str:
    if FULL_NAME_COLUMN in table.header:
        return row[FULL_NAME_COLUMN]
    first = row.get(FIRST_NAME_COLUMN, "")
    last = row.get(LAST_NAME_COLUMN, "")
    return f"{first} {last}".strip()


@dataclasses.dataclass(frozen=True)
class FillReport:
    filled: int
    # Keys given that match no row (late enrolments, staff, typos)
    unmatched_keys: list[str]
    # Data rows (1-based) that got no value
    unfilled_rows: list[int]


@dataclasses.dataclass
class MoodleSheet:
    """A Moodle export with participant rows: its table and identity columns.
    Worksheet and Gradebook add the columns of their upload path."""

    table: Table
    # Identity kind -> column, for the kinds the export has
    identity: dict[str, str]

    @property
    def rows(self) -> list[dict[str, str]]:
        return self.table.rows

    def full_name(self, row: dict[str, str]) -> str:
        return _full_name(self.table, row)

    def column_of(self, kind: str) -> str:
        if kind not in self.identity:
            raise MoodleFormatError(
                f"{self.table.source}: no {kind} column "
                f"(identity columns: {', '.join(self.identity.values()) or 'none'})"
            )
        return self.identity[kind]

    def rows_by(self, kind: str) -> dict[str, dict[str, str]]:
        """Rows by each identity of the given kind; an identity in two rows is
        an error."""
        column = self.column_of(kind)
        result: dict[str, dict[str, str]] = {}
        numbers: dict[str, int] = {}
        for number, row in enumerate(self.rows, start=1):
            for identity in identities(row[column]):
                if identity in result:
                    raise MoodleFormatError(
                        f"{self.table.source}: data rows {numbers[identity]} and "
                        f"{number} have the same {column}"
                    )
                result[identity] = row
                numbers[identity] = number
        return result

    def write(self, path: pathlib.Path) -> None:
        """Write the export for Moodle's upload (CSV), with all columns and the
        header order as read."""
        from .tables import write_table

        write_table(self.table, path)


@dataclasses.dataclass(frozen=True)
class FillTarget:
    """Where grades (and feedback) go in a sheet."""

    sheet: MoodleSheet
    grade: str
    # None if the export has no feedback column
    feedback: str | None

    def fill(
        self,
        values: Mapping[str, tuple[str, str | None]],
        *,
        by: str,
        missing: Missing = "keep",
    ) -> FillReport:
        """Set grade and feedback from values: identity of the kind `by` ->
        (grade, feedback or None to leave it). With missing="error", every row
        needs a value; on any error nothing is changed."""
        sheet = self.sheet
        column = sheet.column_of(by)
        if self.feedback is None and any(feedback for _, feedback in values.values()):
            raise MoodleFormatError(
                f"{sheet.table.source}: no feedback column for {self.grade!r}"
            )
        keys = {}
        for key in values:
            normalised = identities(key)
            if len(normalised) != 1:
                raise ValueError(f"{key!r} is not one identity")
            keys[normalised[0]] = key
        assignments: list[tuple[dict[str, str], tuple[str, str | None]]] = []
        unfilled = []
        used = set()
        for number, row in enumerate(sheet.rows, start=1):
            matching = [
                identity for identity in identities(row[column]) if identity in keys
            ]
            if len(matching) > 1:
                raise MoodleFormatError(
                    f"{sheet.table.source}: data row {number} matches several "
                    f"given identities in {column}"
                )
            if matching:
                used.add(matching[0])
                assignments.append((row, values[keys[matching[0]]]))
            else:
                unfilled.append(number)
        if missing == "error" and unfilled:
            raise MoodleFormatError(
                f"{sheet.table.source}: no value for data rows "
                f"{', '.join(map(str, unfilled))}"
            )
        for row, (grade, feedback) in assignments:
            row[self.grade] = grade
            if feedback is not None and self.feedback is not None:
                row[self.feedback] = feedback
        return FillReport(
            filled=len(assignments),
            unmatched_keys=[
                keys[identity] for identity in keys if identity not in used
            ],
            unfilled_rows=unfilled,
        )


@dataclasses.dataclass
class Worksheet(MoodleSheet):
    """An assignment's grading worksheet ("Download grading worksheet"), which
    Moodle matches by Identifier on upload."""

    identifier: str = IDENTIFIER_COLUMN
    grade: str = ""
    feedback: str = ""

    @classmethod
    def read(cls, path: pathlib.Path, *, sheet: str | None = None) -> "Worksheet":
        table = read_table(path, sheet=sheet)
        if IDENTIFIER_COLUMN not in table.header:
            raise MoodleFormatError(
                f"{path}: no {IDENTIFIER_COLUMN!r} column, not a grading worksheet"
            )
        for number, row in enumerate(table.rows, start=1):
            if not IDENTIFIER_PATTERN.fullmatch(row[IDENTIFIER_COLUMN]):
                raise MoodleFormatError(
                    f"{path}: data row {number} has no 'Participant <number>' "
                    "identifier"
                )
        return cls(
            table=table,
            identity=_identity_columns(table),
            grade=_single(table, GRADE_PREFIX, GRADE_PREFIX, GRADE_EXCLUDED),
            feedback=_single(table, FEEDBACK_COLUMN, FEEDBACK_PREFIX),
        )

    @property
    def target(self) -> FillTarget:
        return FillTarget(self, self.grade, self.feedback)

    def participant_id(self, row: dict[str, str]) -> str:
        """The assignment's participant number of a row (not an identity: it
        differs between assignments)."""
        match = IDENTIFIER_PATTERN.fullmatch(row[self.identifier])
        assert match is not None  # checked when reading
        return match[1]


@dataclasses.dataclass(frozen=True)
class GradeItem:
    """A grade item of the gradebook export, e.g. "Assignment: Judge Password"
    with columns by display ("Real", "Feedback", ...)."""

    type: str
    name: str
    columns: dict[str, str]


@dataclasses.dataclass
class Gradebook(MoodleSheet):
    """The course gradebook export ("Grades" > Export). Moodle's import matches
    rows by a user field chosen at import time and maps the columns there, so
    there is no Identifier; other columns are written back unchanged."""

    @classmethod
    def read(cls, path: pathlib.Path, *, sheet: str | None = None) -> "Gradebook":
        table = read_table(path, sheet=sheet)
        sheet_ = cls(table=table, identity=_identity_columns(table))
        if not sheet_.identity:
            raise MoodleFormatError(f"{path}: no identity column")
        return sheet_

    def items(self) -> list[GradeItem]:
        """The grade items, in column order."""
        columns: dict[tuple[str, str], dict[str, str]] = {}
        for column in self.table.header:
            if match := GRADEBOOK_ITEM_PATTERN.fullmatch(column):
                key = (match["type"], match["name"])
                columns.setdefault(key, {})[match["display"]] = column
        return [
            GradeItem(type=type_, name=name, columns=by_display)
            for (type_, name), by_display in columns.items()
        ]

    def target(self, name: str) -> FillTarget:
        """The columns of a grade item, by its name ("Judge Password") or type
        and name ("Assignment: Judge Password")."""
        items = [
            item
            for item in self.items()
            if name in (item.name, f"{item.type}: {item.name}")
        ]
        if len(items) != 1:
            known = ", ".join(f"{item.type}: {item.name}" for item in self.items())
            found = "several" if items else "no"
            raise MoodleFormatError(
                f"{self.table.source}: {found} grade item {name!r} (items: {known})"
            )
        (item,) = items
        if GRADEBOOK_GRADE_DISPLAY not in item.columns:
            raise MoodleFormatError(
                f"{self.table.source}: grade item {name!r} has no "
                f"({GRADEBOOK_GRADE_DISPLAY}) column, only "
                f"{', '.join(item.columns.values())}"
            )
        return FillTarget(
            self,
            item.columns[GRADEBOOK_GRADE_DISPLAY],
            item.columns.get(GRADEBOOK_FEEDBACK_DISPLAY),
        )


# Participants


@dataclasses.dataclass(frozen=True)
class Participant:
    # Identity kind -> raw value, for the kinds present
    identity: dict[str, str]
    first_name: str
    last_name: str


def read_participants(path: pathlib.Path) -> list[Participant]:
    """The participants of Moodle's JSON download (participants page)."""
    try:
        data = path.read_bytes()
    except OSError as e:
        raise MoodleFormatError(f"{path}: {e.strerror}") from e
    text, _, _ = _decode_text(path, data, None)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as e:
        raise MoodleFormatError(
            f"{path}: invalid JSON at line {e.lineno} column {e.colno}"
        ) from None
    # The download is a list of tables; the participants are the first
    if isinstance(value, list) and value and isinstance(value[0], list):
        value = value[0]
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise MoodleFormatError(f"{path}: expected a list of participant records")
    participants = []
    for record in value:
        identity = {}
        for kind, keys in PARTICIPANT_KEYS.items():
            for key in keys:
                if record.get(key) not in (None, ""):
                    identity[kind] = str(record[key])
                    break
        participants.append(
            Participant(
                identity=identity,
                first_name=str(record.get(PARTICIPANT_FIRST_NAME_KEY) or ""),
                last_name=str(record.get(PARTICIPANT_LAST_NAME_KEY) or ""),
            )
        )
    return participants


# Choice responses


@dataclasses.dataclass(frozen=True)
class ChoiceResponse:
    # Identity kind -> raw value, for the identity columns of the export
    identity: dict[str, str]
    choice: str
    name: str


def read_choice_responses(
    path: pathlib.Path, *, choice_column: str = CHOICE_COLUMN
) -> list[ChoiceResponse]:
    """The responses of a choice download (tab-separated text or xlsx)."""
    table = read_table(path)
    if choice_column not in table.header:
        raise MoodleFormatError(f"{path}: no {choice_column!r} column")
    columns = _identity_columns(table)
    if not columns:
        raise MoodleFormatError(f"{path}: no identity column")
    return [
        ChoiceResponse(
            identity={
                kind: row[column] for kind, column in columns.items() if row[column]
            },
            choice=row[choice_column],
            name=_full_name(table, row),
        )
        for row in table.rows
    ]


# The two uses


def login_text(login: str, password: str) -> str:
    return LOGIN_TEXT.format(login=login, password=password)


def send_login_data(
    target: FillTarget,
    credentials: Mapping[str, tuple[str, str]],
    *,
    by: str,
    grade: str = LOGIN_GRADE,
    text: Callable[[str, str], str] = login_text,
    missing: Missing = "keep",
) -> FillReport:
    """Put login name and password into the feedback of each matched row, with
    grade 1 (a worksheet's target, or a gradebook item's). credentials:
    identity of the kind `by` -> (login, password). Rows without credentials
    (staff, late enrolments) stay as they are by default."""
    return target.fill(
        {
            key: (grade, text(login, password))
            for key, (login, password) in credentials.items()
        },
        by=by,
        missing=missing,
    )


def send_feedback(
    target: FillTarget,
    results: Mapping[str, tuple[float | str, str | None]],
    *,
    by: str,
    grade_format: str = "{:.2f}",
    missing: Missing = "error",
) -> FillReport:
    """Set grade and feedback (HTML, or None to leave it) from results:
    identity of the kind `by` -> (grade, feedback). Numbers are formatted with
    grade_format. Every row needs a result unless missing="keep": a final grade
    is not skipped silently."""
    return target.fill(
        {
            key: (
                grade if isinstance(grade, str) else grade_format.format(grade),
                feedback,
            )
            for key, (grade, feedback) in results.items()
        },
        by=by,
        missing=missing,
    )
