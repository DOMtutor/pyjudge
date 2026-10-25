# Known Issues and Open Points

What remains of the code review of October 2026 after the fixes of the same month.
Each item is a proposal or a known limitation, not a decision.

## Design

* **Keys vs. names (by design).**
  The writer (`database/_users.py`, `_problems.py`, `_contest.py`, ...) identifies every object by its key, stored as DOMjudge's `externalid`, so all other properties can change and are synchronised on the next upload.
  The reader (`database/_query.py`, exports) works by names (contest short name, team name, login), so it also works on databases not created by pydomjudge.
* **problemtools coupling** goes through private attributes (`p.output_validators._validators`, `submissions._submissions`) and `argparse.Namespace` stand-ins (`kattis.py`, `_fuzzer.py`).
  Every problemtools update can break these silently; a thin adapter module would localise the damage (see also the long-term TODO "migrate away from problemtools").
* **Compile scripts** in `repository/compiler/` follow DOMjudge 9.0.1; `compiler/README.md` lists the deviations (among them `pypy3 -O`, intended) and how local verification differs.

## Limitations and untested parts

* **Integration coverage.**
  `tests/integration/run.sh` uploads the examples into a real DOMjudge and checks its pages, the API, its configuration check, that a second upload changes nothing, a changed jury solution, the self-service against DOMjudge's login and, with `JUDGE=1`, the verdicts of the jury solutions and a hello world per language through the judgehost.
  Not yet covered: removing team members, removing contest problems (and the guard against deleting team submissions), multi-file submissions in exports.
  The tests use the official images; the DOMtutor ones work with `DOMJUDGE_DOMSERVER_IMAGE`/`DOMJUDGE_JUDGEHOST_IMAGE`, and only languages of the example repository (c, java, python) go through the judge.
* **Web tools keep state per process.**
  The fuzzer's running jobs and the self-service's limit of failed password attempts live in memory, so both run with a single gunicorn worker.
  Fuzzing jobs on the same problem run one after another.
* **Port in DOMjudge's redirects.**
  The `DOMJUDGE_PUBLIC_PORT` start script is in domjudge-packaging (`docker/domserver/scripts/start.d/45-public-port.sh`), not yet in the images on Docker Hub; until their next build, `docs/docker-compose.yml` on a port other than 80 redirects to port 80. `tests/integration/compose.yml` keeps its own copy as a compose config for the official images.
* **Jury submissions of removed teams stay.**
  `create_problem_submissions` only matches existing submissions of the teams it is given, so submissions of an author team that no longer exists are not deleted.
* **A dry run would need a diff.**
  The second upload of an unchanged setup executes 83 statements that change no rows (`run.sh` prints the table): the writer upserts everything, so `--dry-run` (idea 1 below) cannot just log statements but has to compare with the database.

## Breaking changes in this series

* `SubmissionVerdict` and `TestcaseVerdict` are replaced by one `pydomjudge.model.Verdict`, whose values are DOMjudge's result strings (`timelimit`, not `time-limit`).
  Old `instance.json` files and exports still load; new exports write the DOMjudge spelling.
* `dt_judge_export contest|submissions` takes the contest's short name (the contest `UPDATE` used to write the key into the short name).
* `pydomjudge.scripts.db`, `pydomjudge.scripts.util` and `kattis.add_arguments`/`from_args` are replaced by `pydomjudge.scripts._cli`.
* `update_user_password(cursor, user_key, password_hash)` takes a key and a hash instead of a `User`.
* `examples/minimal` and `examples/teal2026` are merged into `examples/`; its `script.py` takes the options before the subcommand (`python script.py --pretty -O contest.json contest`).
* The optional extras `web` and `evaluate` of the development version were never released; all dependencies are part of the package again.

* One `pyjudge` command with subcommands replaces the `dt_*` commands, which remain as deprecated aliases with their old arguments.
  `dt_judge_upload check` is `pyjudge upload cleanup`.
* `--debug` (anywhere on the command line) adds the traceback to errors, which were always printed with one before; the fuzzer has no Flask `--debug` switch any more, and the self-service no `-v`.
* `docs/docker-compose.yml` uses `incaseoftrouble/domtutor_domserver` and `domtutor_judgehost` (`incaseoftrouble/domserver` is gone), the web port is `DOMJUDGE_PORT` (default 12345), and the judgehost gets `DOMJUDGE_JUDGE_PASSWORD` (it fell back to the image default before).
* The compile scripts are DOMjudge 9.0.1's with the deviations of `compiler/README.md` (flags and behaviour of the earlier versions differ, e.g. Rust compile errors are compile errors now).
  Julia is no default language any more.
* When a jury solution changes, its earlier versions in DOMjudge are marked invalid (ignored) instead of being judged alongside the new one.
* Self-service: registration is at `/register` (`/` redirects to it when it is the only service), the configuration is checked strictly (unknown keys are errors), and the app does not start without the team category. pyjudge hashes passwords with bcrypt cost 7 like DOMjudge (12 before; existing hashes stay valid).

## Usability ideas

Not implemented; for the owner to decide.
(Done in this series: the `pyjudge` command with completion, `pyjudge.yaml`, `pyjudge check`, `pyjudge problem new`, friendlier errors, the fuzzer's language list and progress, the compose profile `tools`.)

1. `--dry-run` for `pyjudge upload` that prints the planned creates, updates and deletes, and a change summary at the end of every run (see "A dry run would need a diff" above).
2. Password workflow: generate initial passwords for a roster and write a distribution CSV instead of requiring bcrypt hashes in `users.json`.
3. `pyjudge export grades`: the best verdict per team and problem as CSV for grading.
4. `pyjudge doctor`: check the system dependencies (checktestdata, pypy3, latexmk, javac, database reachability) and print install hints.
5. Progress output during verification and statement builds (problem, step, duration).
6. Self-service: restrict registration to a roster or invitation codes (`username_pattern` covers simple cases), optional e-mail field.
