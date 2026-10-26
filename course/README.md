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
For JSON files (Moodle's participants download) it prints the shape: list lengths, and the keys and value types of the records.

## Column names

The Moodle views find columns by the names in a `MoodleColumns` instance, whose defaults are the English names observed in a Moodle site's exports.
A site with other names, for example in another language, passes its own instance:

```python
columns = MoodleColumns(
    identifier="Bezeichner",
    feedback="Feedback als Kommentar",
    identity={"email": ("E-Mail-Adresse",)},
)
worksheet = Worksheet.read(path, columns=columns)
```

## Roster

`pydomjudge_course.roster` keeps who is who between Moodle and DOMjudge in a CSV file at a path the course chooses, with one row per identity value (student ID, email, username).
An entry's id, DOMjudge keys, login and display name are fixed when the person is first added, and identities only accumulate, so logins and passwords stay valid.
New rows are appended; whether the file is tracked in git is up to the course.

The file may be edited by hand, for example after an error about identities of two different entries, which names the roster rows to look at.
All rows of an id must have the same keys and display name, and an identity value may belong to one id only.

A matched row's new values are added to its entry.
A first value of a kind (a first username) or another `|` part of a field that matched is an expected alias.
A different value of a kind the entry already has is reported and logged as a warning naming the entry's roster rows: a changed email, a student ID the university reassigned (the entry keeps its login and password), or a student ID reused for a different person, whose wrong merge has to be split by hand.

## Student data

The functions read and write files with student data (Moodle exports, rosters, submissions).
They never write inside this package and do not log cell values or names above DEBUG.
Whether such files are tracked in a course repository is the course's decision; tests use synthetic data only.

## Known limitations

- A worksheet downloaded as xlsx whose "Last modified (grade)" cells are real dates (not text) is written back with those dates in ISO 8601.
  Whether Moodle's upload reads them as the same time (it uses them to skip grades changed after the download) is not verified; downloading the worksheet as CSV avoids the question.
