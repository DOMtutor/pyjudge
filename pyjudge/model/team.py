import dataclasses
import enum
from typing import List, Optional, Dict

from .user import User


class TeamCategory(enum.Enum):
    # TODO This currently is hardcoded - but should be sufficient for any kind of course?
    # TODO However this could be used to manage access permissions on a multi-course instance
    Jury = "jury"
    Solution = "solution"
    Author = "author"
    Participants = "participants"
    Hidden = "hidden"

    @staticmethod
    def parse(data):
        for category in TeamCategory:
            if category.value == data:
                return category
        raise KeyError(data)

    def serialize(self):
        return self.value


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
    name: str
    display_name: str
    members: List[User]
    category: Optional[TeamCategory]
    affiliation: Optional[Affiliation]

    @staticmethod
    def parse(data, user_by_name: Dict[str, User], affiliation_by_name: Dict[str, Affiliation]):
        category = TeamCategory.parse(data["category"]) if "category" in data else None
        affiliation = affiliation_by_name[data["affiliation"]] if "affiliation" in data else None

        if not data.get("members", []):
            raise ValueError("Invalid team")
        members: List[User] = []
        for member_name in data["members"]:
            if member_name not in user_by_name:
                raise ValueError(f"Non-existing user {member_name}")
            members.append(user_by_name[member_name])

        return Team(
            name=data["name"],
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
            "category": self.category.serialize(),
            "members": [user.login_name for user in self.members]
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
