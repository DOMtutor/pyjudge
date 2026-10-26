"""The roster: who is who, between Moodle and DOMjudge.

Each entry is one person with a canonical id (from which its DOMjudge user
key, login and team key were made when it was added) and its identities
(student IDs, emails, usernames), which Moodle exports are matched by. The
roster is append-only: entries and keys never change, and identities only
accumulate, so logins and passwords stay valid. It holds identities only:
categories, roles, passwords and enrolment come from the course when it
makes its users.

The roster file is a CSV with one row per identity value::

    id,kind,value,user_key,login,team_key,display_name,added

It may be edited by hand, for example to fix a conflict: all rows of an id
must agree on keys and display name, and a value belongs to one id only.
New rows are appended in the file's own delimiter and encoding.

Identities are matched in a declared priority (student ID, email, username by
default). An input row that matches an entry adds its new values to it:
- a value of a kind the entry has no value of yet (a first username), or
  another "|" part of a field that matched, is an expected new alias;
- a different value of a kind the entry already has is a changed identity,
  whatever its priority: a changed email, a student ID the university
  reassigned (the entry keeps its id, login and password), or a student ID
  reused for a different person. It is reported and logged as a warning
  naming the entry's roster rows, so that a wrong merge can be split by hand.
Identities that point to two different entries are an error naming the
roster rows to look at.
"""

import csv
import dataclasses
import datetime
import logging
import pathlib
import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Literal, TypeVar

from pydomjudge.model import Affiliation, Team, TeamCategory, User, UserRole

from .moodle import DEFAULT_COLUMNS, MoodleColumns, MoodleSheet, Participant
from .tables import TableError, read_table

log = logging.getLogger(__name__)

T = TypeVar("T")

ROSTER_COLUMNS = (
    "id",
    "kind",
    "value",
    "user_key",
    "login",
    "team_key",
    "display_name",
    "added",
)
KINDS = ("student_id", "email", "username")


class RosterError(TableError):
    """An inconsistent roster or input; the message names roster rows and
    input rows, never values."""


@dataclasses.dataclass(frozen=True)
class IdentityConfig:
    # The kind whose value (its first "|" part) becomes the id of a new entry
    canonical: str = "student_id"
    # The kinds to match by, highest priority first
    match: tuple[str, ...] = ("student_id", "email", "username")
    # Templates of the keys of a new entry, with {id}
    user_key: str = "{id}"
    login: str = "{id}"
    team_key: str = "t_{id}"
    # Identity value (any kind) -> id, for people without (or with another)
    # canonical identity, e.g. staff by email
    overrides: Mapping[str, str] = dataclasses.field(default_factory=dict)
    columns: MoodleColumns = DEFAULT_COLUMNS

    def __post_init__(self):
        unknown = {self.canonical, *self.match} - set(KINDS)
        if unknown:
            raise ValueError(f"unknown identity kinds: {', '.join(sorted(unknown))}")


@dataclasses.dataclass(frozen=True)
class Person:
    """One input row: identity kind -> raw value (may hold "|"), and names."""

    identity: Mapping[str, str]
    first_name: str = ""
    last_name: str = ""
    # Row number in the input, for messages
    row: int = 0


def people_from_sheet(sheet: MoodleSheet) -> list[Person]:
    """The rows of a worksheet or gradebook as people."""
    people = []
    for number, row in enumerate(sheet.rows, start=1):
        columns = sheet.columns
        first = row.get(columns.first_name, "")
        last = row.get(columns.last_name, "")
        if not (first or last) and columns.full_name in row:
            first = row[columns.full_name]
        people.append(
            Person(
                identity={
                    kind: row[column]
                    for kind, column in sheet.identity.items()
                    if row[column]
                },
                first_name=first,
                last_name=last,
                row=number,
            )
        )
    return people


def people_from_participants(participants: Sequence[Participant]) -> list[Person]:
    return [
        Person(
            identity=participant.identity,
            first_name=participant.first_name,
            last_name=participant.last_name,
            row=number,
        )
        for number, participant in enumerate(participants, start=1)
    ]


@dataclasses.dataclass
class Entry:
    id: str
    user_key: str
    login: str
    team_key: str
    display_name: str
    # Kind -> raw values (stripped, case kept), in the order added
    values: dict[str, list[str]] = dataclasses.field(default_factory=dict)
    # Roster file rows (1-based data rows) of this entry
    rows: list[int] = dataclasses.field(default_factory=list)

    def first(self, kind: str) -> str | None:
        values = self.values.get(kind)
        return values[0] if values else None


@dataclasses.dataclass(frozen=True)
class AddReport:
    new_ids: list[str]
    # (entry id, kind): a first value of a kind, or another "|" part of a
    # field that matched
    new_aliases: list[tuple[str, str]]
    # (entry id, kind): a different value of a kind the entry already had
    # (changed email, reassigned or reused student ID)
    changed_identities: list[tuple[str, str]]
    # Input rows without a canonical identity or override
    skipped_rows: list[int]


class Roster:
    def __init__(self, path: pathlib.Path, config: IdentityConfig):
        self.path = path
        self.config = config
        self.entries: list[Entry] = []
        self._by_id: dict[str, Entry] = {}
        # (kind, normalised value) -> entry id
        self._index: dict[tuple[str, str], str] = {}
        self._new_rows: list[dict[str, str]] = []
        self._row_count = 0
        self._delimiter = ","
        self._encoding = "utf-8"

    # Reading

    @classmethod
    def open(cls, path: pathlib.Path, config: IdentityConfig) -> "Roster":
        """The roster at path; empty if there is no file yet."""
        roster = cls(path, config)
        if path.exists():
            roster._load()
        return roster

    def _normal(self, value: str) -> str:
        return value.strip().casefold()

    def _load(self) -> None:
        table = read_table(self.path)
        missing = [name for name in ROSTER_COLUMNS if name not in table.header]
        if missing:
            raise RosterError(f"{self.path}: missing columns {', '.join(missing)}")
        self._delimiter, self._encoding = table.delimiter, table.encoding
        for number, row in enumerate(table.rows, start=1):
            if not (row["id"] and row["kind"] and row["value"]):
                raise RosterError(f"{self.path}: row {number} lacks id, kind or value")
            if row["kind"] not in KINDS:
                raise RosterError(f"{self.path}: row {number} has an unknown kind")
            entry = self._by_id.get(row["id"])
            if entry is None:
                entry = Entry(
                    id=row["id"],
                    user_key=row["user_key"],
                    login=row["login"],
                    team_key=row["team_key"],
                    display_name=row["display_name"],
                )
                self._by_id[entry.id] = entry
                self.entries.append(entry)
            elif (entry.user_key, entry.login, entry.team_key, entry.display_name) != (
                row["user_key"],
                row["login"],
                row["team_key"],
                row["display_name"],
            ):
                raise RosterError(
                    f"{self.path}: rows {entry.rows[0]} and {number} have the same "
                    "id but different keys or display name"
                )
            key = (row["kind"], self._normal(row["value"]))
            owner = self._index.get(key)
            if owner is not None and owner != entry.id:
                raise RosterError(
                    f"{self.path}: rows {self._by_id[owner].rows[0]} and {number} "
                    "give the same identity to different ids"
                )
            self._index[key] = entry.id
            entry.values.setdefault(row["kind"], []).append(row["value"].strip())
            entry.rows.append(number)
        self._row_count = len(table.rows)

    # Matching

    def _split(self, raw: str) -> list[str]:
        separator = self.config.columns.identity_separator
        return [part.strip() for part in raw.split(separator) if part.strip()]

    def _hits(
        self, identity: Mapping[str, str], kinds: Sequence[str]
    ) -> dict[str, set[str]]:
        """Kind -> ids of the entries its values match."""
        hits: dict[str, set[str]] = {}
        for kind in kinds:
            for value in self._split(identity.get(kind) or ""):
                if (owner := self._index.get((kind, self._normal(value)))) is not None:
                    hits.setdefault(kind, set()).add(owner)
        return hits

    def _conflict(self, ids: Iterable[str], where: str) -> RosterError:
        rows = "; ".join(
            f"rows {', '.join(map(str, self._by_id[entry_id].rows))}"
            for entry_id in sorted(ids)
        )
        return RosterError(
            f"{where}: the identities belong to different roster entries "
            f"({self.path}: {rows}); fix the roster by hand"
        )

    def find(
        self,
        identity: Mapping[str, str],
        *,
        kinds: Sequence[str] | None = None,
        unknown: Literal["error", "none"] = "error",
        where: str = "input",
    ) -> Entry | None:
        """The entry of identity (kind -> raw value), by the given or the
        configured kinds."""
        hits = self._hits(identity, kinds or self.config.match)
        ids = set().union(*hits.values()) if hits else set()
        if len(ids) > 1:
            raise self._conflict(ids, where)
        if not ids:
            if unknown == "none":
                return None
            raise RosterError(f"{where}: no roster entry for these identities")
        return self._by_id[ids.pop()]

    def by_login(self, login: str) -> Entry:
        for entry in self.entries:
            if entry.login == login:
                return entry
        raise RosterError("no roster entry with this login")

    def by_team(self, team_key: str) -> Entry:
        for entry in self.entries:
            if entry.team_key == team_key:
                return entry
        raise RosterError("no roster entry with this team key")

    def resolve_teams(self, keyed: Mapping[str, T]) -> dict[str, T]:
        """Values keyed by any identity (e.g. deadline extensions by student ID
        or email), keyed by team key."""
        result: dict[str, T] = {}
        for number, (key, value) in enumerate(keyed.items(), start=1):
            ids = {
                owner
                for kind in KINDS
                for part in self._split(str(key))
                if (owner := self._index.get((kind, self._normal(part)))) is not None
            }
            where = f"entry {number} of {len(keyed)}"
            if len(ids) > 1:
                raise self._conflict(ids, where)
            if not ids:
                raise RosterError(f"{where}: no roster entry for this identity")
            team_key = self._by_id[ids.pop()].team_key
            if team_key in result:
                raise RosterError(f"{where}: a second value for the same team")
            result[team_key] = value
        return result

    # Adding

    def _new_id(self, identity: Mapping[str, str]) -> str | None:
        overrides = {
            self._normal(key): value for key, value in self.config.overrides.items()
        }
        for kind in KINDS:
            for part in self._split(identity.get(kind) or ""):
                if (override := overrides.get(self._normal(part))) is not None:
                    return override
        parts = self._split(identity.get(self.config.canonical) or "")
        return parts[0] if parts else None

    def _append(self, entry: Entry, kind: str, value: str) -> None:
        self._row_count += 1
        entry.values.setdefault(kind, []).append(value)
        entry.rows.append(self._row_count)
        self._index[(kind, self._normal(value))] = entry.id
        self._new_rows.append(
            {
                "id": entry.id,
                "kind": kind,
                "value": value,
                "user_key": entry.user_key,
                "login": entry.login,
                "team_key": entry.team_key,
                "display_name": entry.display_name,
                "added": datetime.date.today().isoformat(),
            }
        )

    def add(
        self,
        people: Iterable[Person],
        *,
        display_name: Callable[[Person, str], str],
    ) -> AddReport:
        """Add new people and new identities of known ones; save() writes them.
        display_name(person, id) is used for new entries only."""
        new_ids, new_aliases, changed, skipped = [], [], [], []
        kinds = self.config.match
        for person in people:
            where = f"input row {person.row}"
            hits = self._hits(person.identity, kinds)
            ids = set().union(*hits.values()) if hits else set()
            if len(ids) > 1:
                raise self._conflict(ids, where)
            if ids:
                entry = self._by_id[ids.pop()]
                order = [*kinds, *(kind for kind in KINDS if kind not in kinds)]
                existing_rows = ", ".join(map(str, entry.rows))
                for kind in order:
                    values = self._split(person.identity.get(kind) or "")
                    known = {
                        self._normal(value) for value in entry.values.get(kind, [])
                    }
                    added = [
                        value for value in values if self._normal(value) not in known
                    ]
                    if not added:
                        continue
                    # A first value of a kind, or another "|" part of a field
                    # that matched, is expected; a different value of a kind
                    # the entry has (changed email, reassigned or reused
                    # student ID) is a change to look at
                    expected = not known or kind in hits
                    for value in added:
                        self._append(entry, kind, value)
                    if expected:
                        new_aliases.append((entry.id, kind))
                    else:
                        changed.append((entry.id, kind))
                        log.warning(
                            "%s: another %s for the roster entry of rows %s; "
                            "if this is a different person, split the entry by hand",
                            where,
                            kind,
                            existing_rows,
                        )
                continue
            entry_id = self._new_id(person.identity)
            if entry_id is None:
                skipped.append(person.row)
                continue
            if entry_id in self._by_id:
                # An override, or a canonical value that is an id already
                rows = ", ".join(map(str, self._by_id[entry_id].rows))
                raise RosterError(
                    f"{where}: its new id is the id of the roster entry of "
                    f"{self.path} rows {rows}, but no identity matches; fix the "
                    "roster or the overrides by hand"
                )
            entry = Entry(
                id=entry_id,
                user_key=self.config.user_key.format(id=entry_id),
                login=self.config.login.format(id=entry_id),
                team_key=self.config.team_key.format(id=entry_id),
                display_name=display_name(person, entry_id),
            )
            self._by_id[entry_id] = entry
            self.entries.append(entry)
            for kind in KINDS:
                for value in self._split(person.identity.get(kind) or ""):
                    self._append(entry, kind, value)
            new_ids.append(entry_id)
        return AddReport(new_ids, new_aliases, changed, skipped)

    def save(self) -> None:
        """Append the new rows to the roster file (created if missing)."""
        if not self._new_rows:
            return
        exists = self.path.exists()
        if exists:
            ends_with_newline = self.path.read_bytes().endswith((b"\n", b"\r"))
        with self.path.open("a", encoding=self._encoding, newline="") as f:
            writer = csv.DictWriter(f, ROSTER_COLUMNS, delimiter=self._delimiter)
            if not exists:
                writer.writeheader()
            elif not ends_with_newline:
                f.write("\r\n")
            writer.writerows(self._new_rows)
        self._new_rows = []

    # DOMjudge

    def credentials(
        self,
        passwords: Mapping[str, str],
        *,
        kind: str,
        ids: Iterable[str] | None = None,
    ) -> dict[str, tuple[str, str]]:
        """Every value of `kind` -> (login, password), for the entries with a
        password (all, or those in ids, e.g. AddReport.new_ids so that a re-run
        for late enrolments sends login data to the new people only); for
        send_login_data(..., by=kind)."""
        selected = set(ids) if ids is not None else None
        return {
            value: (entry.login, passwords[entry.id])
            for entry in self.entries
            if entry.id in passwords and (selected is None or entry.id in selected)
            for value in entry.values.get(kind, [])
        }


def read_wordlist(path: pathlib.Path) -> list[str]:
    """The words for passwords, one per line, capitalized."""
    with path.open(mode="rt", encoding="utf-8") as f:
        return [line.strip().capitalize() for line in f.readlines()]


def password_for(canonical_id: str, wordlist: Sequence[str]) -> str:
    """Three words, determined by the id: the same password on every run."""
    return "".join(random.Random(x=bytes(canonical_id, "utf-8")).choices(wordlist, k=3))


def users_and_teams(
    roster: Roster,
    *,
    category: TeamCategory | Callable[[Entry], TeamCategory],
    affiliation: Affiliation | None,
    passwords: Mapping[str, str] | None = None,
    ids: Iterable[str] | None = None,
    role: UserRole = UserRole.Participant,
    email: bool = False,
) -> tuple[list[User], list[Team]]:
    """One user and one-person team per roster entry (all, or those in ids),
    with the password hashed if given and the entry's first email if email."""
    selected = set(ids) if ids is not None else None
    users, teams = [], []
    for entry in roster.entries:
        if selected is not None and entry.id not in selected:
            continue
        password = passwords.get(entry.id) if passwords else None
        user = User(
            key=entry.user_key,
            login_name=entry.login,
            display_name=entry.display_name,
            email=entry.first("email") if email else None,
            role=role,
            password_hash=User.hash_password(password) if password else None,
        )
        users.append(user)
        teams.append(
            Team(
                key=entry.team_key,
                name=entry.team_key,
                display_name=entry.display_name,
                members=[user],
                category=category
                if isinstance(category, TeamCategory)
                else category(entry),
                affiliation=affiliation,
            )
        )
    return users, teams
