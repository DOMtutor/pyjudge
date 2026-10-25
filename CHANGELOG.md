# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [semantic versioning](https://semver.org/) (before 1.0, minor versions may break things).

## 0.4.0 - 2026-10-25

### Added

- `pyjudge`: one command with subcommands (`upload`, `export`, `problem`, `check`, `serve`, `init`, `config`, `make-admin`, `anonymize`) and shell completion (argcomplete); the shared options (`--db`, `--repository`, `--instance`, `--debug`, `--log`) work before and after the command name.
- `pyjudge.yaml`: a project configuration (database, repository, instance, users, contest), found by walking up from the working directory, with a user-wide fallback in `$XDG_CONFIG_HOME/pyjudge/`; `pyjudge init` writes one, `pyjudge config` shows the values in use and where they come from.
- `pyjudge check`: a consistency report of the database (teams without users, users without team, disabled languages with pending submissions, problems in no contest, unexpected jury verdicts, ...).
- `pyjudge problem new KEY`: a problem scaffold (statement, sample, submissions, optionally generator and seed) that passes verification as is.
- Self-service: configurable services, registration (`/register`, with team category and optional username pattern) and password change (`/password`) with a limit of failed attempts.
- Fuzzer: the language list comes from the repository (`GET /languages`), runs report progress, and a cancelled run stops.
- Compose profile `selfservice` in `docs/docker-compose.yml` for the self-service.
- Integration tests against a real DOMjudge (`tests/integration/run.sh`, with `JUDGE=1` also through a judgehost), a pytest suite, CI with ruff and ty.
- Error messages name the file and the location of the problem (`--debug` adds the traceback).
- `pydomjudge.database.category_exists`, `find_user_id`, `find_team_id` and `find_login` (returning a `UserLogin`), which the self-service uses instead of its own SQL.

### Changed

- **Breaking:** Python 3.12 or newer.
- **Breaking:** one `pydomjudge.model.Verdict` replaces `SubmissionVerdict` and `TestcaseVerdict`; its values are DOMjudge's result strings (`timelimit`, not `time-limit`).
- **Breaking:** the `pyjudge` command replaces the `dt_*` commands; `dt_judge_upload check` is `pyjudge upload cleanup`, and `dt_default_settings` is `pyjudge init`.
- **Breaking:** `pyjudge export contest|submissions` takes the contest's short name (the contest update used to write the key into the short name).
- **Breaking:** `pydomjudge.scripts.db`, `pydomjudge.scripts.util` and `kattis.add_arguments`/`from_args` are replaced by `pydomjudge.scripts._cli`; `update_user_password(cursor, user_key, password_hash)` takes a key and a hash instead of a `User`.
- **Breaking:** `--debug` adds the traceback to errors (they were always printed with one); the fuzzer has no Flask `--debug` switch any more, and the self-service no `-v`.
- **Breaking:** the compile scripts are DOMjudge 9.0.1's with the deviations listed in `repository/compiler/README.md`; flags and behaviour of the earlier scripts differ (for example, Rust compile errors are compile errors now).
- **Breaking:** when a jury solution changes, its earlier versions in DOMjudge are marked invalid instead of being judged alongside the new one.
- **Breaking:** self-service registration is at `/register` (`/` redirects to it when it is the only service), its configuration is checked strictly (unknown keys are errors), and it does not start without its team category.
- **Breaking:** `docs/docker-compose.yml` uses the images `incaseoftrouble/domtutor_domserver` and `domtutor_judgehost`, the web port `DOMJUDGE_PORT` (default 12345), and passes `DOMJUDGE_JUDGE_PASSWORD` to the judgehost (it fell back to the image default before).
- **Breaking:** `examples/minimal` and `examples/teal2026` are merged into `examples/`; its `script.py` takes the options before the subcommand.
- **Breaking:** unknown keys in `instance.json` (including its settings), contest files, `users.json` and the repository `config.yaml` are errors instead of being ignored; for example, the scoring settings of pydomjudge 0.2 (`score`) are now `scoring`.
  An unknown language in `config.yaml` names the file and the known languages.
- Passwords are hashed with bcrypt cost 7, as DOMjudge does (12 before; existing hashes stay valid).
- A repeated upload of unchanged data changes no rows; languages are created in a fixed order.
- problemtools is used only through `pydomjudge.repository._problemtools`.
- The database writer is split into one module per entity, with one SQL style.

### Removed

- **Breaking:** Julia as a default language (DOMjudge has no compile script for it, and the DOMtutor judgehost no Julia).
- The optional extras `web` and `evaluate` of the development version (never released); all dependencies are part of the package.

### Fixed

- Database writer and reader bugs, export round trips, and repository loading (compiler overrides, generators, verification marker); see the git history of this version for the details.
- A second `with` block on the same problem used removed copies of its submissions (every fuzzer job after the first failed).
- The judgehost in `docs/docker-compose.yml` got the wrong password, and DOMjudge's redirects lost the published port.

## 0.3.3 and earlier

Not recorded here; see the git history.
