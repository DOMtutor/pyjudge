# Changelog of pydomjudge-course

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the package is versioned separately from pydomjudge.

## Unreleased

### Added

- The package skeleton, a member of the pyjudge uv workspace.
- `pydomjudge_course.tables`: `read_table` for CSV, TSV and xlsx (encoding and BOM detection, delimiter sniffing, every cell a string) and `write_table`, which keeps header order, encoding, delimiter and BOM so that exports can be imported again.
  `python -m pydomjudge_course.tables FILE...` shows format and column names, never cells.
