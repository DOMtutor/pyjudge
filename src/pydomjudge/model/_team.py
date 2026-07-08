from pydantic import BaseModel

from ._user import User
from pydomjudge.util import FrozenSequence


class TeamCategory(BaseModel, frozen=True):
    key: str
    name: str
    color: str
    visible: bool
    order: int
    self_registration: bool


class SystemCategory:
    Jury = TeamCategory(
        key="jury",
        name="Jury",
        color="lightgreen",
        visible=False,
        order=10,
        self_registration=False,
    )
    Solution = TeamCategory(
        key="solution",
        name="Solutions",
        color="green",
        visible=False,
        order=20,
        self_registration=False,
    )
    Author = TeamCategory(
        key="author",
        name="Authors",
        color="green",
        visible=False,
        order=30,
        self_registration=False,
    )
    System = TeamCategory(
        key="system",
        name="System",
        color="purple",
        visible=False,
        order=40,
        self_registration=False,
    )

    @classmethod
    def values(cls):
        return [cls.Jury, cls.Solution, cls.Author, cls.System]


class DefaultCategory:
    Participants = TeamCategory(
        key="participants",
        name="Participants",
        color="lightgray",
        visible=True,
        order=5,
        self_registration=False,
    )
    Hidden = TeamCategory(
        key="hidden",
        name="Participants (hidden)",
        color="gray",
        visible=False,
        order=5,
        self_registration=False,
    )

    @classmethod
    def all(cls):
        return [cls.Participants, cls.Hidden]


class Affiliation(BaseModel, frozen=True):
    key: str
    short_name: str
    name: str
    country: str | None


class Team(BaseModel, frozen=True):
    key: str
    name: str
    display_name: str
    members: FrozenSequence[User]
    category: TeamCategory | None
    affiliation: Affiliation | None

    def __str__(self):
        return f"Team({self.name})"
