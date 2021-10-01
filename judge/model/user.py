import dataclasses
import enum
from typing import Optional


class UserRole(enum.Enum):
    Participant = "participant"
    Admin = "admin"
    Organizer = "organizer"
    Jury = "jury"

    @staticmethod
    def parse(value):
        for role in UserRole:
            if value == role.serialize():
                return role
        raise KeyError(value)

    def serialize(self):
        return self.value


@dataclasses.dataclass
class JudgeUser(object):
    name: str
    display_name: str
    email: Optional[str]
    role: UserRole

    @staticmethod
    def parse(data):
        return JudgeUser(data["name"], data["display_name"], data["email"], UserRole.parse(data["role"]))

    def serialize(self):
        return {"name": self.name, "display_name": self.display_name, "email": self.email,
                "role": self.role.serialize()}

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return isinstance(other, JudgeUser) and self.name == other.name

