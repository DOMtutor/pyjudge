"""The roster, on synthetic people only."""

import logging
import pathlib
import random

import bcrypt
import pytest

from pydomjudge.model import DefaultCategory, SystemCategory
from pydomjudge.scripts.upload import UsersDescription
from pydomjudge_course.moodle import Participant, Worksheet, send_login_data
from pydomjudge_course.roster import (
    IdentityConfig,
    Person,
    Roster,
    RosterError,
    password_for,
    people_from_participants,
    people_from_sheet,
    read_wordlist,
    users_and_teams,
)
from pydomjudge_course.tables import read_table

WORDS = ["Apple", "Banana", "Cherry", "Damson", "Elder", "Fig", "Grape"]


def _person(
    row: int,
    student_id: str = "",
    email: str = "",
    username: str = "",
    first="A",
    last="Example",
):
    identity = {"student_id": student_id, "email": email, "username": username}
    return Person(
        identity={kind: value for kind, value in identity.items() if value},
        first_name=first,
        last_name=last,
        row=row,
    )


def _name(person: Person, _id: str) -> str:
    return f"{person.first_name} {person.last_name.upper()}"


@pytest.fixture
def path(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "roster.csv"


def _roster(path: pathlib.Path, **config) -> Roster:
    return Roster.open(path, IdentityConfig(**config))


def test_new_entries_and_reopen(path: pathlib.Path):
    roster = _roster(path, team_key="p_{id}")
    report = roster.add(
        [
            _person(1, "9000001", "Alice@Example.org", "alice1", first="Alice"),
            _person(2, " 9000002|9000012 ", "bob@example.org", first="Bob"),
        ],
        display_name=_name,
    )
    assert report.new_ids == ["9000001", "9000002"]
    roster.save()
    assert read_table(path).header == (
        "id", "kind", "value", "user_key", "login", "team_key", "display_name", "added",
    )  # fmt: skip

    again = _roster(path, team_key="p_{id}")
    bob = again.find({"student_id": "9000012"})
    assert bob is not None
    # The first "|" part is the id, the second an alias of the same entry
    assert (bob.id, bob.login, bob.user_key, bob.team_key) == (
        "9000002", "9000002", "9000002", "p_9000002",
    )  # fmt: skip
    assert bob.display_name == "Bob EXAMPLE"
    alice = again.find({"email": "alice@example.org"})
    assert alice is not None and alice.first("email") == "Alice@Example.org"
    assert again.by_login("9000001") is alice
    assert again.by_team("p_9000002") is bob


def test_rerun_appends_only_what_is_new(path: pathlib.Path, caplog):
    roster = _roster(path)
    roster.add([_person(1, "9000001", "alice@example.org")], display_name=_name)
    roster.save()
    before = path.read_bytes()

    roster = _roster(path)
    report = roster.add(
        [_person(1, "9000001", "alice@example.org")], display_name=_name
    )
    roster.save()
    assert report == type(report)([], [], [], [])
    assert path.read_bytes() == before

    # A new student, and a new email (the old one stays an alias)
    roster = _roster(path)
    report = roster.add(
        [
            _person(4, "9000001", "alice.new@example.org"),
            _person(5, "9000003", "carol@example.org"),
        ],
        display_name=_name,
    )
    roster.save()
    assert report.new_ids == ["9000003"]
    assert report.new_aliases == []
    assert report.changed_identities == [("9000001", "email")]
    again = _roster(path)
    assert again.find({"email": "alice@example.org"}) is again.find(
        {"email": "alice.new@example.org"}
    )
    assert path.read_bytes().startswith(before)


def test_reassigned_student_id_keeps_login_and_password(path: pathlib.Path, caplog):
    roster = _roster(path)
    roster.add([_person(1, "9000001", "alice@example.org")], display_name=_name)
    roster.save()
    first = roster.find({"student_id": "9000001"})
    assert first is not None
    password = password_for(first.id, WORDS)

    roster = _roster(path)
    with caplog.at_level(logging.WARNING, logger="pydomjudge_course.roster"):
        report = roster.add(
            [_person(7, "9100001", "alice@example.org")], display_name=_name
        )
    roster.save()
    assert report.changed_identities == [("9000001", "student_id")]
    assert report.new_ids == []
    assert (
        "input row 7: another student_id for the roster entry of rows 1, 2"
        in caplog.text
    )
    assert "9100001" not in caplog.text and "alice" not in caplog.text

    entry = _roster(path).find({"student_id": "9100001"})
    assert entry is not None
    assert (entry.id, entry.login) == ("9000001", "9000001")
    assert password_for(entry.id, WORDS) == password


def test_identities_of_two_entries_are_an_error(path: pathlib.Path):
    roster = _roster(path)
    roster.add(
        [
            _person(1, "9000001", "alice@example.org"),
            _person(2, "9000002", "bob@example.org"),
        ],
        display_name=_name,
    )
    roster.save()
    roster = _roster(path)
    with pytest.raises(
        RosterError, match=r"input row 3: .*rows 1, 2; rows 3, 4"
    ) as error:
        roster.add([_person(3, "9000001", "bob@example.org")], display_name=_name)
    assert "9000001" not in str(error.value) and "bob" not in str(error.value)
    with pytest.raises(RosterError, match="different roster entries"):
        roster.find({"student_id": "9000001", "email": "bob@example.org"})


def test_overrides_and_skipped_rows(path: pathlib.Path):
    roster = _roster(path, overrides={"Lecturer@Example.org": "meggendo"})
    report = roster.add(
        [
            _person(1, email="lecturer@example.org"),
            _person(2, email="ta@example.org"),
            _person(3, "9000001", "alice@example.org"),
        ],
        display_name=_name,
    )
    assert report.new_ids == ["meggendo", "9000001"]
    assert report.skipped_rows == [2]
    with pytest.raises(RosterError, match="its new id is the id of the roster entry"):
        roster.add([_person(4, "meggendo")], display_name=_name)


def test_find_by_kinds_and_unknown(path: pathlib.Path):
    roster = _roster(path)
    roster.add(
        [_person(1, "9000001", "alice@example.org", "alice1")], display_name=_name
    )
    assert roster.find({"username": "ALICE1"}) is not None
    assert roster.find({"username": "alice1"}, kinds=("email",), unknown="none") is None
    with pytest.raises(RosterError, match="input: no roster entry"):
        roster.find({"email": "nobody@example.org"})


def test_hand_edited_roster(path: pathlib.Path):
    header = "id;kind;value;user_key;login;team_key;display_name;added\n"
    path.write_text(
        header + "9000001;student_id;9000001;9000001;9000001;t_9000001;A;2026-10-01"
    )
    roster = _roster(path, team_key="t_{id}")
    roster.add([_person(2, "9000002")], display_name=_name)
    roster.save()
    text = path.read_text()
    assert text.splitlines()[2].startswith("9000002;student_id;9000002;")
    assert len(_roster(path).entries) == 2

    path.write_text(
        header
        + "1;student_id;1;1;1;t_1;A;\n"
        + "1;email;a@example.org;1;1;t_1;Other name;\n"
    )
    with pytest.raises(
        RosterError, match="rows 1 and 2 have the same id but different keys"
    ):
        _roster(path)
    path.write_text(header + "1;student_id;1;1;1;t_1;A;\n2;student_id;1;2;2;t_2;B;\n")
    with pytest.raises(RosterError, match="rows 1 and 2 give the same identity"):
        _roster(path)


def test_password_compatible_with_the_courses(tmp_path: pathlib.Path):
    wordlist = tmp_path / "wordlist.txt"
    wordlist.write_text("apple\nbanana\ncherry\n")
    words = read_wordlist(wordlist)
    assert words == ["Apple", "Banana", "Cherry"]
    # random.choices seeded with the id
    expected = "".join(random.Random(x=bytes("9000001", "utf-8")).choices(words, k=3))
    assert password_for("9000001", words) == expected


def test_users_and_teams(path: pathlib.Path):
    roster = _roster(path, team_key="p_{id}")
    roster.add(
        [
            _person(1, "9000001", "Alice@Example.org"),
            _person(2, "9000002", "bob@example.org"),
        ],
        display_name=_name,
    )
    passwords = {entry.id: password_for(entry.id, WORDS) for entry in roster.entries}
    users, teams = users_and_teams(
        roster,
        category=lambda e: (
            DefaultCategory.Hidden
            if e.id == "9000002"
            else DefaultCategory.Participants
        ),
        affiliation=None,
        passwords=passwords,
        email=True,
    )
    assert [u.login_name for u in users] == ["9000001", "9000002"]
    assert users[0].email == "Alice@Example.org"
    password_hash = users[0].password_hash
    assert password_hash is not None and password_hash.startswith("$2b$07$")
    assert bcrypt.checkpw(passwords["9000001"].encode(), password_hash.encode())
    assert [(t.key, t.category) for t in teams] == [
        ("p_9000001", DefaultCategory.Participants),
        ("p_9000002", DefaultCategory.Hidden),
    ]
    description = UsersDescription(users=users, teams=teams, affiliations=[])
    categories = {c.key: c for c in DefaultCategory.all() + [SystemCategory.Jury]}
    again = UsersDescription.model_validate_json(
        description.model_dump_json(), context={"category_by_key": categories}
    )
    assert [t.key for t in again.teams] == ["p_9000001", "p_9000002"]

    users, teams = users_and_teams(
        roster, category=DefaultCategory.Participants, affiliation=None, ids=["9000002"]
    )
    assert [u.key for u in users] == ["9000002"] and users[0].password_hash is None


def test_credentials_and_send_login_data(path: pathlib.Path, tmp_path: pathlib.Path):
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "Identifier",
            "First name",
            "Last name",
            "Student ID",
            "Email address",
            "Grade",
            "Feedback comments",
        ]
    )
    sheet.append(
        [
            "Participant 1",
            "Alice",
            "Example",
            "9000001",
            "alice@example.org",
            None,
            None,
        ]
    )
    sheet.append(
        [
            "Participant 2",
            "Bob",
            "Example",
            "9000002|9000012",
            "bob@example.org",
            None,
            None,
        ]
    )
    workbook.save(tmp_path / "worksheet.xlsx")
    worksheet = Worksheet.read(tmp_path / "worksheet.xlsx")

    roster = _roster(path)
    report = roster.add(people_from_sheet(worksheet), display_name=lambda p, id: id)
    assert report.new_ids == ["9000001", "9000002"]
    passwords = {entry.id: password_for(entry.id, WORDS) for entry in roster.entries}
    credentials = roster.credentials(passwords, kind="student_id")
    assert credentials["9000012"] == ("9000002", passwords["9000002"])
    fill = send_login_data(worksheet.target, credentials, by="student_id")
    assert fill.filled == 2 and fill.unfilled_rows == []
    assert worksheet.rows[1]["Feedback comments"].startswith(
        "Your login name: 9000002\n"
    )


def test_people_from_participants(path: pathlib.Path):
    people = people_from_participants(
        [
            Participant(
                identity={"email": "a@example.org", "student_id": "1"},
                first_name="A",
                last_name="B",
            )
        ]
    )
    assert people == [
        Person(
            identity={"email": "a@example.org", "student_id": "1"},
            first_name="A",
            last_name="B",
            row=1,
        )
    ]


def test_resolve_teams(path: pathlib.Path):
    roster = _roster(path)
    roster.add(
        [
            _person(1, "9000001", "alice@example.org"),
            _person(2, "9000002", "bob@example.org"),
        ],
        display_name=_name,
    )
    # Extensions keyed by student ID or email, wherever they come from
    assert roster.resolve_teams(
        {"9000001": {"days": 2}, "bob@example.org": {"days": 1}}
    ) == {
        "t_9000001": {"days": 2},
        "t_9000002": {"days": 1},
    }
    with pytest.raises(RosterError, match="entry 1 of 1: no roster entry"):
        roster.resolve_teams({"nobody": {}})
    with pytest.raises(
        RosterError, match="entry 2 of 2: a second value for the same team"
    ):
        roster.resolve_teams({"9000001": 1, "alice@example.org": 2})


def test_email_change_is_a_warned_change(path: pathlib.Path, caplog):
    roster = _roster(path)
    roster.add([_person(1, "9000001", "alice@example.org")], display_name=_name)
    with caplog.at_level(logging.WARNING, logger="pydomjudge_course.roster"):
        report = roster.add(
            [_person(2, "9000001", "alice@new.example.org")], display_name=_name
        )
    assert report.changed_identities == [("9000001", "email")]
    assert report.new_aliases == []
    assert "input row 2: another email for the roster entry of rows 1, 2" in caplog.text
    assert "example.org" not in caplog.text


def test_reused_student_id_warns_with_the_rows_to_split(path: pathlib.Path, caplog):
    roster = _roster(path)
    roster.add([_person(1, "9000001", "alice@example.org")], display_name=_name)
    # Alice gets a new student ID; the old one stays an alias
    roster.add([_person(2, "9100001", "alice@example.org")], display_name=_name)
    roster.save()
    # The university gives the old ID to someone else, who hits Alice's entry
    roster = _roster(path)
    with caplog.at_level(logging.WARNING, logger="pydomjudge_course.roster"):
        report = roster.add(
            [_person(3, "9000001", "dave@example.org")], display_name=_name
        )
    roster.save()
    assert report.new_ids == []
    assert report.changed_identities == [("9000001", "email")]
    assert (
        "input row 3: another email for the roster entry of rows 1, 2, 3" in caplog.text
    )
    assert "split the entry by hand" in caplog.text
    assert "dave" not in caplog.text and "9000001" not in caplog.text
    # Rows 1-3 belong to Alice, row 4 is Dave's email: the rows to split
    assert [row["value"] for row in read_table(path).rows] == [
        "9000001",
        "alice@example.org",
        "9100001",
        "dave@example.org",
    ]


def test_expected_new_aliases(path: pathlib.Path, caplog):
    roster = _roster(path)
    roster.add([_person(1, "9000002", "bob@example.org")], display_name=_name)
    with caplog.at_level(logging.WARNING, logger="pydomjudge_course.roster"):
        # A first username, and a second "|" part next to the known one
        report = roster.add(
            [_person(2, "9000002|9000012", "bob@example.org", "bob2")],
            display_name=_name,
        )
    assert sorted(report.new_aliases) == [
        ("9000002", "student_id"),
        ("9000002", "username"),
    ]
    assert report.changed_identities == []
    assert caplog.text == ""


def test_credentials_for_new_entries_only(path: pathlib.Path):
    roster = _roster(path)
    roster.add([_person(1, "9000001", "alice@example.org")], display_name=_name)
    report = roster.add([_person(2, "9000002", "bob@example.org")], display_name=_name)
    passwords = {entry.id: password_for(entry.id, WORDS) for entry in roster.entries}
    assert roster.credentials(passwords, kind="email", ids=report.new_ids) == {
        "bob@example.org": ("9000002", passwords["9000002"])
    }
    assert len(roster.credentials(passwords, kind="email")) == 2
