# Changelog of pydomjudge-course

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the package is versioned separately from pydomjudge.

## Unreleased

### Added

- The package skeleton, a member of the pyjudge uv workspace.
- `pydomjudge_course.tables`: `read_table` for CSV, TSV and xlsx (encoding and BOM detection, delimiter sniffing, every cell a string) and `write_table`, which keeps header order, encoding, delimiter and BOM so that exports can be imported again.
  `python -m pydomjudge_course.tables FILE...` shows format and column names, never cells.
  For JSON files it shows the shape (list lengths, the keys and value types of records), never values, and keys of other objects only as a count.
- `pydomjudge_course.moodle`: the grading worksheet (identity columns, grade and feedback column, `fill` by identity and `write` with Identifier and header unchanged), participants from the JSON download, choice responses, and the two uses `send_login_data` (rows without credentials stay) and `send_feedback` (every row needs a result unless `missing="keep"`).
  The format assumptions are constants in one place, observed in the exports of an English Moodle site.
