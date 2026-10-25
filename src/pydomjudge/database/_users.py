"""Affiliations, team categories, users and teams.

Part of the writer, which works by key; see the package docstring.
"""

import itertools
import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from pydomjudge.exc import ElementNotFoundError
from pydomjudge.model import (
    Affiliation,
    SystemCategory,
    Team,
    TeamCategory,
    User,
    UserRole,
)

from ._db import DBCursor as Cursor, field_not_in_list, list_param

log = logging.getLogger(__name__)


user_role_to_database = {
    UserRole.Participant: ["team"],
    UserRole.Admin: ["admin"],
    UserRole.Organizer: ["admin", "jury", "team"],
    UserRole.Jury: ["jury", "team"],
}


def _find_category_ids(
    cursor: Cursor, categories: list[TeamCategory]
) -> Mapping[TeamCategory, int]:
    cursor.execute("SELECT categoryid, externalid FROM team_category")

    database_to_category: dict[str, TeamCategory] = {
        category.key: category for category in categories
    }
    category_ids_by_key: Mapping[str, int] = {
        key: category_id for category_id, key in cursor
    }
    category_ids: Mapping[TeamCategory, int] = {
        database_to_category[key]: category_id
        for key, category_id in category_ids_by_key.items()
        if key in database_to_category
    }
    log.debug("Found existing categories %s", ", ".join(category_ids_by_key.keys()))
    return category_ids


def _find_affiliation_ids(
    cursor: Cursor, affiliations: Collection[Affiliation]
) -> dict[Affiliation, int]:
    if not affiliations:
        return {}
    affiliations_by_key = {affiliation.key: affiliation for affiliation in affiliations}
    # noinspection SqlType
    cursor.execute(
        f"SELECT affilid, externalid FROM team_affiliation "
        f"WHERE externalid IN {list_param(affiliations)}",
        tuple(affiliation.key for affiliation in affiliations),
    )
    return {affiliations_by_key[key]: affiliation_id for affiliation_id, key in cursor}


def _find_user_ids(cursor: Cursor, users: Collection[User]) -> dict[User, int]:
    if not users:
        return {}
    users_by_key = {user.key: user for user in users}
    # noinspection SqlType
    cursor.execute(
        f"SELECT userid, externalid FROM `user` WHERE externalid IN {list_param(users)}",
        tuple(user.key for user in users),
    )
    return {users_by_key[key]: user_id for user_id, key in cursor}


def _find_team_ids(cursor: Cursor, teams: Collection[Team]) -> dict[Team, int]:
    if not teams:
        return {}
    teams_by_key: dict[str, Team] = {team.key: team for team in teams}
    # noinspection SqlType
    cursor.execute(
        f"SELECT teamid, externalid FROM team WHERE externalid IN {list_param(teams)}",
        tuple(team.key for team in teams),
    )
    return {teams_by_key[key]: team_id for team_id, key in cursor}


def update_categories(
    cursor: Cursor, categories: list[TeamCategory], lazy=False
) -> Mapping[TeamCategory, int]:
    expected_categories = set(categories) | set(SystemCategory.values())
    expected_categories_by_key = {
        category.key: category for category in expected_categories
    }

    cursor.execute("SELECT categoryid, externalid FROM team_category")
    existing_ids_by_key: Mapping[str, int] = {
        key: category_id for category_id, key in cursor
    }

    if lazy and existing_ids_by_key.keys() == expected_categories_by_key.keys():
        return {
            expected_categories_by_key[name]: category_id
            for name, category_id in existing_ids_by_key.items()
        }

    category_ids_to_delete: Collection[int] = {
        category_id
        for category_key, category_id in existing_ids_by_key.items()
        if category_key not in expected_categories_by_key
    }

    category_ids: dict[TeamCategory, int] = {}

    for category in expected_categories:
        key = category.key
        cursor.execute(
            "SELECT categoryid FROM team_category WHERE externalid = %s", (key,)
        )
        result = cursor.fetchall()
        if result:
            category_id = result[0][0]
            log.debug("Found category %s", key)
        else:
            log.debug("Creating category %s", key)
            cursor.execute(
                "INSERT INTO team_category (name, externalid) VALUES (%s, %s)",
                (category.name, key),
            )
            category_id = cursor.lastrowid

        assert isinstance(category_id, int)
        category_ids[category] = category_id
        cursor.execute(
            "UPDATE team_category "
            "SET name = %s, sortorder = %s, color = %s, visible = %s, allow_self_registration = %s "
            "WHERE categoryid = %s",
            (
                category.name,
                category.order,
                category.color,
                category.visible,
                category.self_registration,
                category_id,
            ),
        )

    if category_ids_to_delete:
        log.info("Deleting %d categories", len(category_ids_to_delete))
        cursor.execute(
            f"UPDATE team SET categoryid = NULL "
            f"WHERE categoryid IN {list_param(category_ids_to_delete)}",
            tuple(category_ids_to_delete),
        )
        cursor.execute(
            f"DELETE FROM team_category WHERE categoryid IN {list_param(category_ids_to_delete)}",
            tuple(category_ids_to_delete),
        )
    return category_ids


def create_or_update_teams(
    cursor: Cursor,
    teams: Collection[Team],
    affiliation_ids: dict[Affiliation, int] | None = None,
    user_ids: dict[User, int] | None = None,
) -> dict[Team, int]:
    log.info("Updating %d teams", len(teams))
    if not teams:
        return {}
    if affiliation_ids is None:
        affiliation_ids = {}
    if user_ids is None:
        user_ids = {}

    categories = set(team.category for team in teams if team.category is not None)
    category_ids = _find_category_ids(cursor, list(categories))
    existing_teams = _find_team_ids(cursor, teams)

    missing_affiliations: set[Affiliation] = (
        set(team.affiliation for team in teams if team.affiliation is not None)
        - affiliation_ids.keys()
    )
    missing_affiliation_ids = _find_affiliation_ids(cursor, missing_affiliations)
    if missing_affiliation_ids.keys() != missing_affiliations:
        raise ElementNotFoundError("Some affiliations do not exist")
    affiliation_ids.update(missing_affiliation_ids)
    missing_users: set[User] = set(
        itertools.chain.from_iterable(
            (member for member in team.members) for team in teams
        )
    )
    missing_user_ids = _find_user_ids(cursor, missing_users)
    if missing_user_ids.keys() != missing_users:
        raise ElementNotFoundError("Some users do not exist")
    user_ids.update(missing_user_ids)

    for team in teams:
        team_category = category_ids[team.category] if team.category else None
        affiliation_id = affiliation_ids[team.affiliation] if team.affiliation else None
        if team in existing_teams:
            team_id = existing_teams[team]
            cursor.execute(
                "UPDATE team SET name = %s, display_name = %s, categoryid = %s, affilid = %s WHERE teamid = %s",
                (team.name, team.display_name, team_category, affiliation_id, team_id),
            )
        else:
            log.debug("Creating team %s", team.name)
            cursor.execute(
                "INSERT INTO team (name, display_name, categoryid, affilid, externalid) "
                "VALUES (%s, %s, %s, %s, %s)",
                (team.name, team.display_name, team_category, affiliation_id, team.key),
            )
            team_id = cursor.lastrowid
            assert team_id is not None
            existing_teams[team] = team_id

        member_ids = [user_ids[user] for user in team.members]
        if member_ids:
            cursor.execute(
                f"UPDATE `user` SET teamid = %s WHERE userid IN {list_param(member_ids)}",
                (team_id, *member_ids),
            )
        # Detach users that are no longer members (all of them for an empty team)
        cursor.execute(
            f"UPDATE `user` SET teamid = NULL "
            f"WHERE teamid = %s AND {field_not_in_list('userid', member_ids)}",
            (team_id, *member_ids),
        )
        if cursor.rowcount:
            log.info("Removed %d users from team %s", cursor.rowcount, team.name)

    return existing_teams


def fetch_user_roles(cursor: Cursor) -> dict[str, int]:
    cursor.execute("SELECT roleid, role FROM role")
    return {role: role_id for role_id, role in cursor}


def create_or_update_affiliations(
    cursor: Cursor, affiliations: Collection[Affiliation]
) -> dict[Affiliation, int]:
    log.info("Updating %d affiliations", len(affiliations))
    if not affiliations:
        return {}
    affiliations_by_key = {affiliation.key: affiliation for affiliation in affiliations}

    # noinspection SqlType
    cursor.execute(
        f"SELECT affilid, externalid FROM team_affiliation "
        f"WHERE externalid IN {list_param(affiliations)}",
        tuple(affiliation.key for affiliation in affiliations),
    )
    affiliation_ids: dict[Affiliation, int] = {
        affiliations_by_key[key]: affiliation_id for affiliation_id, key in cursor
    }
    for affiliation in affiliations:
        if affiliation in affiliation_ids:
            cursor.execute(
                "UPDATE team_affiliation SET "
                "externalid = %s, shortname = %s, name = %s, country = %s, internalcomments = NULL "
                "WHERE affilid = %s",
                (
                    affiliation.key,
                    affiliation.short_name,
                    affiliation.name,
                    affiliation.country,
                    affiliation_ids[affiliation],
                ),
            )
        else:
            cursor.execute(
                "INSERT INTO team_affiliation (externalid, shortname, name, country, internalcomments) "
                "VALUES (%s, %s, %s, %s, NULL) ",
                (
                    affiliation.key,
                    affiliation.short_name,
                    affiliation.name,
                    affiliation.country,
                ),
            )
            assert cursor.lastrowid is not None
            affiliation_ids[affiliation] = cursor.lastrowid
    return affiliation_ids


def create_or_update_users(
    cursor: Cursor, users: Collection[User], overwrite_passwords=False
) -> dict[User, int]:
    log.info("Updating %d users", len(users))
    if not users:
        return {}
    for user in users:
        if user.role not in user_role_to_database:
            raise KeyError(f"Invalid role {user.role}")

    role_ids_by_name = fetch_user_roles(cursor)
    user_ids = _find_user_ids(cursor, users)

    for user in users:
        if user in user_ids:
            user_id = user_ids[user]

            cursor.execute(
                "UPDATE `user` SET username = %s, name = %s, email = %s, enabled = TRUE WHERE userid = %s",
                (user.login_name, user.display_name, user.email, user_id),
            )
            if overwrite_passwords and user.password_hash:
                cursor.execute(
                    "UPDATE `user` SET password = %s WHERE userid = %s",
                    (user.password_hash, user_id),
                )
        else:
            cursor.execute(
                "INSERT INTO `user` (externalid, username, name, email, password, enabled) VALUES (%s, %s, %s, %s, %s, TRUE)",
                (
                    user.key,
                    user.login_name,
                    user.display_name,
                    user.email,
                    user.password_hash,
                ),
            )
            user_id = cursor.lastrowid
            assert user_id is not None
            user_ids[user] = user_id

        user_roles = set(
            role_ids_by_name[role] for role in user_role_to_database[user.role]
        )
        cursor.execute("SELECT roleid FROM userrole WHERE userid = %s", (user_id,))
        current_roles = set(role_id for (role_id,) in cursor)
        obsolete_roles = current_roles - user_roles
        if obsolete_roles:
            cursor.execute(
                f"DELETE FROM userrole WHERE userid = %s AND roleid IN {list_param(obsolete_roles)}",
                (user_id, *obsolete_roles),
            )
        missing_roles = user_roles - current_roles
        for role_id in missing_roles:
            cursor.execute(
                "INSERT INTO userrole (userid, roleid) VALUES (%s, %s)",
                (user_id, role_id),
            )

    return user_ids


def disable_unknown_users(cursor: Cursor, user_login_names: set[str]):
    valid_users = {"admin", "judgehost"}
    valid_users.update(user_login_names)
    # noinspection SqlType
    cursor.execute(
        f"UPDATE `user` SET enabled = FALSE WHERE username NOT IN {list_param(valid_users)}",
        tuple(valid_users),
    )
    if cursor.rowcount:
        log.warning("Disabled %d users", cursor.rowcount)


def update_user_password(cursor: Cursor, user_key: str, password_hash: str):
    """Set the password (a bcrypt hash, see User.hash_password) of a user."""
    cursor.execute(
        "UPDATE `user` SET password = %s WHERE externalid = %s",
        (password_hash, user_key),
    )
    if cursor.rowcount != 1:
        raise ElementNotFoundError(f"No user with key {user_key}")


def category_exists(cursor: Cursor, key: str) -> bool:
    """Whether a team category with this key (externalid) exists."""
    cursor.execute("SELECT 1 FROM team_category WHERE externalid = %s", (key,))
    return cursor.fetchone() is not None


def find_user_id(
    cursor: Cursor, *, key: str | None = None, login_name: str | None = None
) -> int | None:
    """The id of a user with this key or this login name, if there is one."""
    cursor.execute(
        "SELECT userid FROM `user` WHERE externalid = %s OR username = %s LIMIT 1",
        (key, login_name),
    )
    row = cursor.fetchone()
    return None if row is None else row[0]


def find_team_id(
    cursor: Cursor, *, key: str | None = None, name: str | None = None
) -> int | None:
    """The id of a team with this key or this name, if there is one."""
    cursor.execute(
        "SELECT teamid FROM team WHERE externalid = %s OR name = %s LIMIT 1",
        (key, name),
    )
    row = cursor.fetchone()
    return None if row is None else row[0]


@dataclass(frozen=True)
class UserLogin:
    """What authenticating a user needs: key (externalid, None for users made
    outside pyjudge and DOMjudge), password hash (None if unset), whether the
    account is enabled, and the names of its DOMjudge roles."""

    key: str | None
    password_hash: str | None
    enabled: bool
    roles: frozenset[str]


def find_login(cursor: Cursor, login_name: str) -> UserLogin | None:
    """The login record of the user with this login name, if there is one."""
    cursor.execute(
        "SELECT u.externalid, u.password, u.enabled, r.role FROM `user` u "
        "LEFT JOIN userrole ur ON ur.userid = u.userid "
        "LEFT JOIN role r ON r.roleid = ur.roleid "
        "WHERE u.username = %s",
        (login_name,),
    )
    rows = cursor.fetchall()
    if not rows:
        return None
    key, password_hash, enabled, _ = rows[0]
    return UserLogin(
        key=key,
        password_hash=password_hash or None,
        enabled=bool(enabled),
        roles=frozenset(role for *_, role in rows if role is not None),
    )
