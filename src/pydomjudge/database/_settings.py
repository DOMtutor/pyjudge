"""Judge-wide configuration.

Part of the writer, which works by key; see the package docstring.
"""

import json
import logging

from pydomjudge.model import (
    JudgeSettings,
)

from ._db import DBCursor as Cursor

log = logging.getLogger(__name__)


def update_settings(cursor: Cursor, settings: JudgeSettings):
    log.info("Updating judge settings")

    def write(key, value):
        # Not REPLACE: that deletes and re-inserts the row on every upload
        cursor.execute(
            "INSERT INTO configuration (name, value) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE value = VALUES(value)",
            (key, value),
        )

    scoring = settings.scoring
    write("penalty_time", scoring.penalty_time)
    write(
        "results_prio",
        json.dumps(
            {
                verdict.value: str(priority)
                for verdict, priority in scoring.result_priority.items()
            }
        ),
    )

    judging = settings.judging
    write("memory_limit", judging.memory_limit)
    write("output_limit", judging.output_limit)
    write("timelimit_overshoot", f'"{judging.time_overshoot}"')
    write("sourcesize_limit", judging.source_size_limit)
    write("sourcefiles_limit", judging.source_file_limit)
    write("script_memory_limit", judging.script_memory_limit)
    write("script_timelimit", judging.script_time_limit)
    write("script_filesize_limit", judging.script_size_limit)
    write("output_storage_limit", judging.output_storage_limit)
    write("output_display_limit", judging.output_display_limit)
    write("lazy_eval_results", judging.lazy_eval)

    display = settings.display
    write("show_pending", display.show_pending)
    write("show_flags", display.show_flags)
    write("show_affiliations", display.show_affiliations)
    write("show_affiliation_logos", display.show_affiliation_logos)
    write("show_teams_submissions", display.show_teams_submissions)
    write("show_sample_output", display.show_sample_output)
    write("show_compile", display.show_compile)

    write("clar_answers", json.dumps(settings.clarification.answers))
