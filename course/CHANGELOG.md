# Changelog of pydomjudge-course

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the package is versioned separately from pydomjudge.

## Unreleased

### Added

- The package skeleton, a member of the pyjudge uv workspace.
- `pydomjudge_course.tables`: `read_table` for CSV, TSV and xlsx (encoding and BOM detection, delimiter sniffing, every cell a string) and `write_table`, which keeps header order, encoding, delimiter and BOM so that exports can be imported again.
  `python -m pydomjudge_course.tables FILE...` shows format and column names, never cells.
  For JSON files it shows the shape (list lengths, the keys and value types of records), never values, and keys of other objects only as a count.
- `pydomjudge_course.moodle`: Moodle sheets with identity columns (`MoodleSheet`: `rows_by`, `write` with all columns unchanged) for both upload paths, the grading worksheet (matched by Identifier) and the gradebook export (matched by a user field chosen at import; grade items with their Real and optional Feedback columns); a `FillTarget` (grade and feedback column) that `send_login_data` (rows without credentials stay) and `send_feedback` (every row needs a result unless `missing="keep"`) fill; participants from the JSON download; choice responses.
  All column names, key names and patterns are fields of `MoodleColumns`, whose defaults were observed in the exports of an English Moodle site.
  Sites with other names (another language, renamed profile fields) pass their own instance to the readers, and a sheet keeps the one it was read with.
