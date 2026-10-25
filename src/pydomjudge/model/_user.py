import enum
from typing import ClassVar

from pydantic import BaseModel


class UserRole(enum.StrEnum):
    Participant = "participant"
    Admin = "admin"
    Organizer = "organizer"
    Jury = "jury"


class User(BaseModel, frozen=True):
    key: str
    login_name: str
    display_name: str
    email: str | None
    role: UserRole
    password_hash: str | None = None

    # DOMjudge hashes with bcrypt at cost 7 (webapp/config/packages/security.yaml);
    # the same cost makes logins equally fast, whoever set the password
    BCRYPT_COST: ClassVar[int] = 7

    @staticmethod
    def generate_salt() -> bytes:
        import bcrypt

        return bcrypt.gensalt(rounds=User.BCRYPT_COST)

    @staticmethod
    def hash_password(password: str, salt: bytes | None = None) -> str:
        import bcrypt

        if salt is None:
            salt = User.generate_salt()

        return bcrypt.hashpw(password.encode(), salt).decode()
