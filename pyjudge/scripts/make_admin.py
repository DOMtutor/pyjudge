import json
import pathlib
import sys

from pyjudge.model import User, UserRole
from pyjudge.scripts.upload import UsersDescription


def main():
    salt = User.generate_salt()
    from getpass import getpass

    name = input("Enter admin user name (default: admin): ")
    if not name:
        name = "admin"
    admin_password = getpass(prompt="Enter admin password: ")
    if not admin_password:
        sys.exit("Empty password")

    admin = User(
        login_name=name,
        display_name=name,
        email=None,
        password_hash=User.hash_password(admin_password, salt),
        role=UserRole.Admin,
    )

    with pathlib.Path("admin.json").open(mode="wt") as f:
        # noinspection PyTypeChecker
        json.dump(
            UsersDescription(users=[admin], teams=[], affiliations=[]).serialize(),
            f,
        )
