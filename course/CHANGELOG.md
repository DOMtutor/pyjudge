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
- `pydomjudge_course.roster`: an append-only roster CSV of identities with a declared match priority, canonical id (the first `|` part, or an override) and key templates.
  It finds entries for Moodle rows, logins, team keys and identity-keyed values such as extensions.
  New values of a matched entry are expected aliases if they are its first of their kind (or another `|` part of a field that matched), and otherwise changed identities (changed email, reassigned or reused student ID), reported with a warning naming the roster rows; identities of two entries are an error naming the roster rows.
  `password_for` and `read_wordlist` make deterministic initial passwords, `credentials` feeds `send_login_data` (for all entries, or only those in `ids=`, e.g. the new ones of a run), and `users_and_teams` makes pydomjudge users and one-person teams with bcrypt cost 7.
- Filling a sheet accepts several identities of one row (`a|b`) when they carry the same value.
