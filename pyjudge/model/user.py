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
    password_hash: Optional[str]
    role: UserRole

    @staticmethod
    def parse(key, data):
        return User(
            key,
            data["display_name"],
            data["email"],
            password_hash=data.get("password_hash", None),
            role=UserRole.parse(data["role"]),
        )

    def serialize(self):
        return filter_if_none({
            "display_name": self.display_name,
            "email": self.email,
            "role": self.role.serialize(),
            "password_hash": self.password_hash
        })

    @property
    def json_ref(self):
        return self.login_name

    def __hash__(self):
        return hash(self.login_name)

    def __eq__(self, other):
        return isinstance(other, User) and self.login_name == other.login_name
