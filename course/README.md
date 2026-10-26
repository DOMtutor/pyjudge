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

`password_for` makes deterministic initial passwords from a course secret: three words of the word list chosen by HMAC-SHA256(secret, id), so nobody can compute them from a student ID without the secret.
`load_secret(path)` reads the secret from `PYJUDGE_PASSWORD_SECRET` or from the file; create one with `python -c "import secrets; print(secrets.token_hex(32))" > path`.
The secret must not be tracked in version control.
Losing it only means other initial passwords for people not created yet: `pyjudge upload users` sets a password only when it creates a user (unless `--overwrite-passwords`), so existing users keep theirs, and students change theirs in the self-service.
`Roster.credentials(..., ids=report.new_ids)` sends login data to the people added in a run only, so a re-run for late enrolments leaves everyone else alone.

## Grading layout

`pydomjudge_course.layout` turns a contest export into files and an evaluation for grading:

```python
deadlines = Deadlines(end, grace=timedelta(minutes=10), late=timedelta(days=1))
# keyed by student ID, email, ...
extensions = roster.resolve_teams({"9000001": timedelta(days=2)})
evaluation = layout_export(
    export_path, Path("grading/data"), deadlines=deadlines, extensions=extensions
)
```

Below the directory it writes `submissions/<problem>/<team>/<time>_<id>/` with every submission under its original file names (also those too late, for plagiarism checks), `final/<team>/<problem>/` with the counting submission (`flatten_single_file=True`: `final/<team>/<problem><suffix>`), and `evaluation.json`.
It owns these three: `submissions/` and `final/` are deleted and rebuilt when the export or the configuration changes, so course outputs belong elsewhere.

A submission is on time until end + grace, late (it counts; the penalty is the course's) until end + late, and too late after that; an extension moves the end.
The counting submission of a team and problem is the last one that is not too late, or what a `select` function returns; give such a function a name, as the cache knows it by name.
`Evaluation.graded()` lists the counting submissions that solve the samples, and every record has its verdict, timing, folder and whether all its files are text (`source`).

## Plagiarism

`pydomjudge_course.plagiarism` needs the extra `pydomjudge-course[plagiarism]` (copydetect, rapidfuzz, pygments).

```python
pairs = find_plagiarism(
    evaluation,
    Path("grading/data"),
    report_directory=Path("grading/data/plagiarism"),
    review_directory=Path("grading/plagiarism"),
)
```

Every source submission of the layout takes part (also those too late; pass `include=` to filter), with a team's near-identical submissions collapsed into one unit.
Per problem, copydetect compares the units of different teams, and a second detector compares their comments, skipping team pairs that are already flagged.
The report directory, rebuilt on every run, holds copydetect's report per problem and an `index.html` with the cases (teams connected by flagged pairs) and the team pairs flagged on several problems.

The review file `<problem>.csv` has a row per flagged team pair with a verdict for each side (`verdict_a`, `verdict_b`), since a team may have copied in one pair and been copied from in another.
Rows keep their verdicts and notes across runs; `review` says what to look at: `new`, `re-review` (other submissions or a different score), or `dropped` (no longer flagged, also when the problem has no submissions any more; delete the row or clear the marker to keep its verdicts).
The reviewer fills in the verdicts and clears `review`.

Verdict kinds map a name to a severity: 0 is not reported, and among a team's reported sides the most severe wins.
The default kinds are `none`, `cited` (the similarity is acknowledged) and `source` (others copied from this side) with 0, `uncited` (a missing citation) with 1 and `copied` with 2.
A course passes its own mapping, for example `{"none": 0, "minor": 1, "major": 2}`, to `read_reviews`, `hearings` and `findings`.
`read_reviews` refuses empty verdicts and open `review` markers.
`findings` gives the most severe reported kind per team and problem with the partners (`write_findings` writes `plagiarism.csv`), and `hearings` gives per team only the pairs where its own side is reported; `write_evidence` links the submissions of those pairs into a folder per team.
A pair whose row was kept although this run did not flag it gets all submissions of both teams to the problem, with a warning.

## Student data

The functions read and write files with student data (Moodle exports, rosters, submissions).
They never write inside this package and do not log cell values or names above DEBUG.
Whether such files are tracked in a course repository is the course's decision; tests use synthetic data only.

## Known limitations

- A worksheet downloaded as xlsx whose "Last modified (grade)" cells are real dates (not text) is written back with those dates in ISO 8601.
  Whether Moodle's upload reads them as the same time (it uses them to skip grades changed after the download) is not verified; downloading the worksheet as CSV avoids the question.
