import dataclasses
import enum
from typing import Optional

from pydomjudge.util import filter_none


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
    password_hash: Optional[str] = None

    @property
    def json_ref(self):
        return self.login_name

    @staticmethod
    def parse(key, data):
        return User(
            key,
            data["display_name"],
            email=data.get("email", None),
            password_hash=data.get("password_hash", None),
            role=UserRole.parse(data["role"]),
        )

    def serialize(self):
        return filter_none(
            {
                "display_name": self.display_name,
                "email": self.email,
                "role": self.role.serialize(),
                "password_hash": self.password_hash,
            }
        )

    @staticmethod
    def generate_salt() -> bytes:
        import bcrypt

        return bcrypt.gensalt()

    @staticmethod
    def hash_password(password: str, salt: bytes) -> str:
        import bcrypt

        return bcrypt.hashpw(password.encode(), salt).decode()

    def __hash__(self):
        return hash(self.login_name)

    def __eq__(self, other):
        return isinstance(other, User) and self.login_name == other.login_name
