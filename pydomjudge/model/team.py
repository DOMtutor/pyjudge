import dataclasses
import enum
from typing import List, Optional, Dict

from .user import User


@dataclasses.dataclass
class TeamCategory(object):
    key: str
    database_name: str
    color: str
    visible: bool
    order: int
    self_registration: bool

    @staticmethod
    def parse(key, data):
        return TeamCategory(
            key,
            data["name"],
            data["color"],
            data["visible"],
            data["order"],
            data["self_registration"],
        )

    @property
    def json_ref(self):
        return self.key

    def serialize(self):
        return {
            "name": self.database_name,
            "color": self.color,
            "visible": self.visible,
            "order": self.order,
            "self_registration": self.self_registration,
        }

    def __hash__(self):
        return hash(self.key)

    def __eq__(self, other):
        return isinstance(other, TeamCategory) and self.key == other.key


class SystemCategory(TeamCategory, enum.Enum):
    Jury = "jury", "Jury", "lightgreen", False, 10, False
    Solution = "solution", "Solutions", "green", False, 20, False
    Author = "author", "Authors", "green", False, 30, False
    System = "system", "System", "purple", False, 40, False


class DefaultCategory(TeamCategory, enum.Enum):
    Participants = "participants", "Participants", "lightgray", True, 5, False
    Hidden = "hidden", "Participants (hidden)", "gray", False, 5, False


@dataclasses.dataclass
class Affiliation(object):
    short_name: str
    name: str
    country: Optional[str]

    @staticmethod
    def parse(key, data):
        return Affiliation(key, data["name"], data.get("country", None))

    @property
    def json_ref(self):
        return self.short_name

    def serialize(self):
        data = {"short_name": self.short_name, "name": self.name}
        if self.country is not None:
            data["country"] = self.country
        return data

    def __hash__(self):
        return hash(self.short_name)

    def __eq__(self, other):
        return isinstance(other, Affiliation) and self.short_name == other.short_name


@dataclasses.dataclass
class Team(object):
    key: str
    name: str
    display_name: str
    members: List[User]
    category: Optional[TeamCategory]
    affiliation: Optional[Affiliation]

    @staticmethod
    def parse(
        name,
        data,
        user_by_name: Dict[str, User],
        affiliation_by_name: Dict[str, Affiliation],
        category_by_name: Dict[str, TeamCategory],
    ):
        category = category_by_name[data["category"]] if "category" in data else None
        affiliation = (
            affiliation_by_name[data["affiliation"]] if "affiliation" in data else None
        )

        if not data.get("members", []):
            raise ValueError("Invalid team")
        members: List[User] = []
        for member_name in data["members"]:
            if member_name not in user_by_name:
                raise ValueError(f"Non-existing user {member_name}")
            members.append(user_by_name[member_name])

        return Team(
            key=name,
            name=name,
            display_name=data["display_name"],
            members=members,
            category=category,
            affiliation=affiliation,
        )

    @property
    def json_ref(self):
        return self.name

    def serialize(self):
        data = {
            "name": self.name,
            "display_name": self.display_name,
            "category": self.category.json_ref,
            "members": [user.login_name for user in self.members],
        }
        if self.affiliation:
            data["affiliation"] = self.affiliation.short_name
        return data

    def __str__(self):
        return f"Team({self.name})"

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return isinstance(other, Team) and self.name == other.name
