import enum

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

    @staticmethod
    def generate_salt() -> bytes:
        import bcrypt

        return bcrypt.gensalt()

    @staticmethod
    def hash_password(password: str, salt: bytes | None = None) -> str:
        import bcrypt

        if salt is None:
            salt = User.generate_salt()

        return bcrypt.hashpw(password.encode(), salt).decode()
