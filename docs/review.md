# Known Issues and Open Points

What remains of the code review of October 2026 after the fixes of the same month.
Each item is a proposal or a known limitation, not a decision.

## Design

* **Keys vs. names (by design).**
  The writer (`database/_users.py`, `_problems.py`, `_contest.py`, ...) identifies every object by its key, stored as DOMjudge's `externalid`, so all other properties can change and are synchronised on the next upload.
  The reader (`database/_query.py`, exports) works by names (contest short name, team name, login), so it also works on databases not created by pydomjudge.
* **`create_problem_submissions`** (`database/_submissions.py`) is 500 lines and re-queries the global configuration for every inserted submission.
* **problemtools coupling** goes through private attributes (`p.output_validators._validators`, `submissions._submissions`) and `argparse.Namespace` stand-ins (`kattis.py`, `_fuzzer.py`).
  Every problemtools update can break these silently; a thin adapter module would localise the damage (see also the long-term TODO "migrate away from problemtools").
* **Compile scripts** in `repository/compiler/*` are copies of DOMjudge's.
  Their origin and DOMjudge version are not recorded, so it is unclear when they need refreshing.

## Limitations and untested parts

* **Integration coverage.**
  `tests/integration/run.sh` uploads the examples into a real DOMjudge and checks its pages, the API, its configuration check and that a second upload changes nothing.
  Not yet covered: removing team members, removing contest problems (and the guard against deleting team submissions), multi-file submissions in exports.
  The judgehost part (`JUDGE=1`) has not run yet: the development machine has a cgroup-v1 `net_cls` mount (Mullvad), see `docs/deployment.md`.
* **Fuzzer state is per process.**
  Running jobs live in the memory of the worker, so the fuzzer must run with a single gunicorn worker.
  `DELETE /submission/<id>` only forgets a run; the thread finishes in the background.
  Two concurrent runs on the same problem share its problemtools context.
* **Jury submissions of removed teams stay.**
  `create_problem_submissions` only matches existing submissions of the teams it is given, so submissions of an author team that no longer exists are not deleted.

## Breaking changes in this series

* `SubmissionVerdict` and `TestcaseVerdict` are replaced by one `pydomjudge.model.Verdict`, whose values are DOMjudge's result strings (`timelimit`, not `time-limit`).
  Old `instance.json` files and exports still load; new exports write the DOMjudge spelling.
* `dt_judge_export contest|submissions` takes the contest's short name (the contest `UPDATE` used to write the key into the short name).
* `pydomjudge.scripts.db`, `pydomjudge.scripts.util` and `kattis.add_arguments`/`from_args` are replaced by `pydomjudge.scripts._cli`.
* `update_user_password(cursor, user_key, password_hash)` takes a key and a hash instead of a `User`.
* `examples/minimal` and `examples/teal2026` are merged into `examples/`; its `script.py` takes the options before the subcommand (`python script.py --pretty -O contest.json contest`).
* The optional extras `web` and `evaluate` of the development version were never released; all dependencies are part of the package again.

## Usability ideas

Not implemented; for the owner to decide.

1. One `dt` entry point with subcommands (`dt upload contest`, `dt kattis check`) and shell completion (`argcomplete`); the nine `dt_*` names are hard to discover.
2. A project configuration file (`pyjudge.yaml` in the course folder with db, repository and instance paths), found by walking up from the working directory; would address GitHub issue #1.
3. `--dry-run` for `dt_judge_upload` that prints the planned creates, updates and deletes, and a change summary at the end of every run.
4. Extend `dt_judge_upload check` into a consistency report: teams without users, users without team, disabled languages with submissions, problems in no contest.
5. `dt_new_problem NAME` to scaffold a problem folder (problem.yaml, statement, sample, generator and seed template, submission directories).
6. Password workflow: generate initial passwords for a roster and write a distribution CSV instead of requiring bcrypt hashes in `users.json`.
7. `dt_judge_export grades`: the best verdict per team and problem as CSV for grading.
8. `dt_doctor`: check the system dependencies (checktestdata, pypy3, latexmk, javac, database reachability) and print install hints.
9. Friendlier errors: render pydantic `ValidationError`s as "field: message" lines and point to `--debug`.
10. Progress output during verification and statement builds (problem, step, duration).
11. Self-service: restrict registration to a roster or invitation codes, optional e-mail field.
12. Fuzzer UI: fetch the language list from the server instead of the static list, and show run progress.
13. A compose profile that runs the self-service and fuzzer image next to DOMjudge from the same `docker-compose.yml`.
