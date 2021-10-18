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
class User(object):
    login_name: str
    display_name: str
    email: Optional[str]
    role: UserRole

    @staticmethod
    def parse(data):
        return User(data["login"], data["display_name"], data["email"], UserRole.parse(data["role"]))

    def serialize(self):
        return {"login": self.login_name, "display_name": self.display_name, "email": self.email,
                "role": self.role.serialize()}

    def __hash__(self):
        return hash(self.login_name)

    def __eq__(self, other):
        return isinstance(other, User) and self.login_name == other.login_name

