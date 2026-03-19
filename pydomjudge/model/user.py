import enum

from pydantic import BaseModel


class UserRole(enum.StrEnum):
    Participant = "participant"
    Admin = "admin"
    Organizer = "organizer"
    Jury = "jury"


class User(BaseModel):
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
    def hash_password(password: str, salt: bytes) -> str:
        import bcrypt

        return bcrypt.hashpw(password.encode(), salt).decode()

    def __hash__(self):
        return hash(self.login_name)

    def __eq__(self, other):
        return isinstance(other, User) and self.login_name == other.login_name
