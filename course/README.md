# pydomjudge-course

Shared plumbing for courses that run their programming assignments on DOMjudge with [pydomjudge](../README.md): reading and writing Moodle exports, a roster that maps Moodle identities to DOMjudge users and teams, the grading layout of a contest export, and plagiarism detection.
Course policy (points, penalties, feedback wording, PDFs, the course file) stays in the course repositories, which call these functions from their own scripts.

The package is a member of the pyjudge uv workspace and uses only pydomjudge's public API.

## Use from a course repository

```toml
[project]
dependencies = ["pydomjudge", "pydomjudge-course"]

[tool.uv.sources]
pydomjudge = { path = "../../DOMtutor/pyjudge", editable = true }
pydomjudge-course = { path = "../../DOMtutor/pyjudge/course", editable = true }
```

## Checking the format of real exports

`python -m pydomjudge_course.tables FILE...` prints each file's format, encoding, delimiter, column names and number of rows, and never a cell value.

## Student data

The functions read and write files with student data (Moodle exports, rosters, submissions).
They never write inside this package and do not log cell values or names above DEBUG.
Keep these files out of version control in the course repositories, and use synthetic data in tests.
