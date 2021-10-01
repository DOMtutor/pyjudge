
# TODO This currently is hardcoded - but should be sufficient for any kind of course?
import dataclasses
import enum
from typing import List, Optional, Dict

from .user import JudgeUser


class TeamCategory(enum.Enum):
    Jury = "jury"
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
    country: str

    @staticmethod
    def parse(data):
        return Affiliation(data["short_name"], data["name"], data["country"])

    def serialize(self):
        return {"short_name": self.short_name, "name": self.name, "country": self.country}

    def __hash__(self):
        return hash(self.short_name)

    def __eq__(self, other):
        return isinstance(other, Affiliation) and self.short_name == other.short_name


@dataclasses.dataclass
class Team(object):
    name: str
    display_name: str
    members: List[JudgeUser]
    category: Optional[TeamCategory]
    affiliation: Optional[Affiliation]

    @staticmethod
    def parse(data, user_by_name: Dict[str, JudgeUser], affiliation_by_name: Dict[str, Affiliation]):
        category = TeamCategory.parse(data["category"]) if "category" in data else None
        affiliation = affiliation_by_name[data["affiliation"]] if "affiliation" in data else None

        if not data.get("members", []):
            raise ValueError("Invalid team")
        members: List[JudgeUser] = []
        for member_name in data["members"]:
            if member_name not in user_by_name:
                raise ValueError(f"Non-existing user {member_name}")
            members.append(user_by_name[member_name])

        return Team(name=data["name"], display_name=data["display_name"], members=members,
                    category=category, affiliation=affiliation)

    def serialize(self):
        return {"name": self.name,
                "display_name": self.display_name,
                "category": self.category.serialize(),
                "members": [user.name for user in self.members],
                "affiliation": self.affiliation.short_name if self.affiliation else None}

    @property
    def json_ref(self):
        return self.name

    def __str__(self):
        return f"Team({self.name})"

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return isinstance(other, Team) and self.name == other.name
