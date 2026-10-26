"""Executables (compile scripts, checkers) and languages.

Part of the writer, which works by key; see the package docstring.
"""

import hashlib
import json
import logging
from collections.abc import Collection

from pydomjudge.model import (
    Executable,
    Language,
)

from ._db import DBCursor as Cursor, field_not_in_list, list_param

log = logging.getLogger(__name__)


def create_or_update_executable(cursor: Cursor, executable: Executable):
    log.debug("Updating executable %s", executable)

    # See domjudge/webapp/src/Entity/ImmutableExecutable.php for the combined hash logic
    file_info = []
    for file_data in executable.contents:
        with file_data.open() as f:
            file_content = f.read()

        filename = file_data.relative_path[-1]
        file_info.append(
            {
                "filename": filename,
                "content": file_content,
                "hash": (hashlib.md5(file_content).hexdigest()),
                "is_executable": filename in ("build", "run"),
            }
        )

    file_info.sort(key=lambda x: x["filename"])
    combined = "".join(
        f"{f['hash']}{f['filename']}{'1' if f['is_executable'] else ''}"
        for f in file_info
    )
    immutable_hash = hashlib.md5(combined.encode()).hexdigest()

    cursor.execute(
        "SELECT immutable_execid FROM immutable_executable WHERE hash = %s ",
        (immutable_hash,),
    )
    result = cursor.fetchone()

    if result:
        immutable_exec_id = result[0]
        log.debug("Reusing existing executable: %s", immutable_exec_id)
    else:
        cursor.execute(
            "INSERT INTO immutable_executable (hash) VALUES (%s) ", (immutable_hash,)
        )
        immutable_exec_id = cursor.lastrowid
        log.debug("Created new executable with id %s", immutable_exec_id)

        for rank_number, file in enumerate(file_info):
            cursor.execute(
                "INSERT INTO executable_file (immutable_execid, filename, ranknumber, file_content, hash, is_executable) "
                "VALUES (%s, %s, %s, %s, %s, %s) ",
                (
                    immutable_exec_id,
                    file["filename"],
                    rank_number,
                    file["content"],
                    file["hash"],
                    file["is_executable"],
                ),
            )

    cursor.execute(
        "INSERT INTO executable (execid, type, description, immutable_execid) "
        "VALUES (%s, %s, %s, %s) "
        "ON DUPLICATE KEY UPDATE "
        "type = VALUES(type), description = VALUES(description), immutable_execid = VALUES(immutable_execid)",
        (
            executable.key,
            executable.executable_type.value,
            executable.description,
            immutable_exec_id,
        ),
    )


def set_default_run(cursor: Cursor, run_script: Executable) -> None:
    """Upload run_script and make it DOMjudge's default_run, the run script of
    every problem without its own (special_run, as interactive problems have,
    takes precedence; DOMjudge's own "run" stays as it is)."""
    create_or_update_executable(cursor, run_script)
    cursor.execute(
        "INSERT INTO configuration (name, value) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE value = VALUES(value)",
        ("default_run", json.dumps(run_script.key)),
    )


def delete_unused_immutable_executables(cursor: Cursor) -> None:
    """Delete file sets no executable refers to any more, after replacing or
    deleting executables (their files go with them, ON DELETE CASCADE)."""
    cursor.execute(
        "DELETE FROM immutable_executable "
        "WHERE immutable_execid NOT IN "
        "(SELECT immutable_execid FROM executable WHERE immutable_execid IS NOT NULL)"
    )
    if cursor.rowcount:
        log.debug("Deleted %d unused executable file sets", cursor.rowcount)


def create_or_update_language(
    cursor: Cursor, language: Language, allow_submit: bool = True
):
    create_or_update_executable(cursor, language.compile_script)
    log.debug("Updating language %s", language)
    cursor.execute(
        "INSERT INTO language (langid, "
        "externalid, compile_script, name, extensions, "
        "time_factor, entry_point_description, require_entry_point, "
        "allow_submit, allow_judge) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE) "
        "ON DUPLICATE KEY UPDATE "
        "externalid = %s, compile_script = %s, name = %s, extensions = %s, "
        "time_factor = %s, entry_point_description = %s, require_entry_point = %s,"
        "allow_submit = %s, allow_judge = TRUE",
        (
            language.key[:32],
            language.key,
            language.compile_script.key,
            language.name,
            json.dumps(sorted(language.extensions)),
            language.time_factor,
            language.entry_point_description,
            language.entry_point_required,
            allow_submit,
            language.key,
            language.compile_script.key,
            language.name,
            json.dumps(sorted(language.extensions)),
            language.time_factor,
            language.entry_point_description,
            language.entry_point_required,
            allow_submit,
        ),
    )


def set_global_languages(
    cursor: Cursor,
    languages: Collection[Language],
    allowed_for_submission: set[str] | None,
):
    if allowed_for_submission is None:
        log.debug("Using all available languages")
        allowed_keys = {language.key for language in languages}
    else:
        allowed_keys = set()
        language_by_key = {language.key: language for language in languages}
        for key in allowed_for_submission:
            if key not in language_by_key:
                raise ValueError(
                    f"Unknown language {key}, languages of the repository are {' '.join(language_by_key.keys())}"
                )
            allowed_keys.add(key)

    cursor.execute("SELECT langid FROM contestlanguage")
    used_keys = set(row[0] for row in cursor)
    cursor.execute("SELECT langid FROM submission")
    used_keys.update({row[0] for row in cursor})
    languages_to_disallow = used_keys - allowed_keys

    log.info(
        "Setting the list of languages to %s",
        ", ".join(sorted(language.name for language in languages)),
    )
    for language in sorted(languages, key=lambda language: language.key):
        create_or_update_language(
            cursor, language, allow_submit=language.key in allowed_keys
        )

    cursor.execute(
        "SELECT langid, compile_script FROM language "
        f"WHERE {field_not_in_list('langid', languages)}",
        tuple(language.key for language in languages),
    )
    languages_to_delete = []
    scripts_to_delete = []
    for language_key, script in cursor:
        if language_key in languages_to_disallow:
            continue
        languages_to_delete.append(language_key)
        if script:
            scripts_to_delete.append(script)
    if scripts_to_delete:
        # noinspection SqlType
        cursor.execute(
            "DELETE FROM executable "
            f"WHERE execid IN {list_param(scripts_to_delete)} AND type = 'compile'",
            tuple(scripts_to_delete),
        )  # Safeguard
    if languages_to_delete:
        # noinspection SqlType
        cursor.execute(
            f"DELETE FROM language WHERE langid IN {list_param(languages_to_delete)}",
            tuple(languages_to_delete),
        )
    if languages_to_disallow:
        log.warning(
            "There are some non-configured languages with submissions or configured in contests: %s",
            ",".join(languages_to_disallow),
        )
        # noinspection SqlType
        cursor.execute(
            f"UPDATE language SET allow_submit = FALSE "
            f"WHERE langid IN {list_param(languages_to_disallow)}",
            tuple(languages_to_disallow),
        )
    # Only now: the compile scripts of deleted languages are gone, too
    delete_unused_immutable_executables(cursor)
