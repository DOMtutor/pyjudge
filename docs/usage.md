# Usage

Everything runs through one command, `pyjudge`, installed with the package (`uv sync`, then `uv run pyjudge ...` or activate the environment):

| Command | Purpose |
|---------|---------|
| `pyjudge upload settings\|users\|contest\|problem\|password\|cleanup` | Synchronise files into the DOMjudge database |
| `pyjudge export contest\|submissions` | Export contest data |
| `pyjudge anonymize` | Anonymize an export |
| `pyjudge problem find\|check\|statements\|samples\|seed` | Work with the problem repository, no database needed |
| `pyjudge make-admin` | Write `admin.json` with one admin user |
| `pyjudge init` | Create `pyjudge.yaml`, `db.yml` and `instance.json` in the current directory |
| `pyjudge config` | Show the settings and the files they come from |
| `pyjudge serve fuzzer\|selfservice` | Web tools, see [tools.md](tools.md) |

`pyjudge --help` and `pyjudge <command> --help` list the options.
Every command accepts `--log LEVEL` (pydomjudge messages, default `INFO`) and `--debug` (everything, including `problemtools`); these and the shared options `--db`, `--repository` and `--instance` can be given anywhere on the command line (`pyjudge --db x upload settings` and `pyjudge upload settings --db x` are the same).

Shell completion (commands, options, problem keys, JSON files) comes with `argcomplete`; enable it with `eval "$(register-python-argcomplete pyjudge)"` in `~/.bashrc` or `~/.zshrc`.

Errors end the command with exit code 1 and a short message.
Problems in a file are listed below its name, for example

```
instance.json: invalid instance settings
  base_time: Input should be a valid number, unable to parse string as a number
  team_categories[0].order: Input should be a valid integer
```

`--debug` adds the traceback.

## Configuration files

The tools are driven by a handful of files that you keep in version control next to your problem repository.
[examples](../examples) contains a complete set; `pyjudge init` starts a new one.

### `pyjudge.yaml`: where the files are

```yaml
database: db.yml          # a file like db.yml, or the connection itself:
#   database: {host: 127.0.0.1, user: domjudge, password_env: DOMJUDGE_DB_PASSWORD}
repository: repository
instance: instance.json
users: users.json         # default of `pyjudge upload users`
contest: contest.json     # default of `pyjudge upload contest`
```

pyjudge uses the first `pyjudge.yaml` in the current directory or one of its parents, so the commands work from anywhere inside the project.
`~/.config/pyjudge/config.yaml` (or in `$XDG_CONFIG_HOME`) has the same keys and fills in what the project file leaves out.
Paths are relative to the file that names them, and command line options (`--db`, `--repository`, `--instance`, file arguments) win over both.
`pyjudge config` shows the effective values and their source.

### `db.yml`: database connection

```yaml
host: 127.0.0.1
port: 3306
user: domjudge
password: ...
database: domjudge
```

Default location: `database` in `pyjudge.yaml`, else `./db.yml`; override with `--db PATH`.
Instead of `password`, `password_env` names an environment variable holding the password.
The tools write to the DOMjudge database directly, so the user needs full access to the `domjudge` schema.

### `instance.json`: judge-wide settings

Created by `pyjudge init`, or from Python via `JudgeInstance`.
Default location: `instance` in `pyjudge.yaml`, else `./instance.json`; override with `--instance PATH`.

| Field | Meaning |
|-------|---------|
| `identifier` | Free-form name of this judge instance |
| `settings.judging` | Memory, output and script limits, time overshoot, lazy evaluation |
| `settings.scoring` | Penalty time and verdict priorities (higher wins when test cases disagree), keyed by DOMjudge's result strings: `correct`, `compiler-error`, `timelimit`, `run-error`, `memory-limit`, `output-limit`, `no-output`, `wrong-answer` |
| `settings.display` | Scoreboard and team-interface display options |
| `settings.clarification` | Canned clarification answers |
| `base_time` | Base time limit in seconds. A problem's time limit is `base_time × time_multiplier` from its `problem.yaml`, rounded to 0.1 s |
| `user_whitelist` | Login names that `pyjudge upload users --disable` never disables (besides `admin` and `judgehost`) |
| `allowed_language_keys` | `null`: every language of the repository may be used for submissions. A list restricts submissions to these keys |
| `team_categories` | Categories to create. The keys `jury`, `solution`, `author`, `system` are reserved for jury solutions |

### `contest.json`: a contest

```json
{
  "key": "example", "short_name": "example", "name": "Example Contest",
  "activation_time": "2026-07-07T12:00:00 Europe/Berlin",
  "start_time": "2026-07-07T13:00:00 Europe/Berlin",
  "end_time": "2026-07-21T12:00:00 Europe/Berlin",
  "freeze_time": null,
  "deactivation_time": "2026-07-22T12:00:00 Europe/Berlin",
  "problems": [{"name": "A", "points": 4, "color": "green", "problem_key": "helloworld"},
               {"name": "B", "points": 4, "color": "blue", "problem_key": "pastryperfection"}],
  "public_scoreboard": false,
  "access": null,
  "warning_message": ""
}
```

Times are `YYYY-MM-DDTHH:MM:SS` followed by an IANA time zone name.
`problems[].name` is the label shown in DOMjudge (usually a letter), `problem_key` the folder name in the repository.
`access` is either `null` (open to all teams) or `{"team_keys": [...], "category_keys": [...]}`.

### `users.json`: users, teams, affiliations

```json
{
  "users": [{"key": "user", "login_name": "user", "display_name": "User", "email": null,
             "role": "participant", "password_hash": "$2b$12$..."}],
  "affiliations": [{"key": "foo", "short_name": "foo", "name": "Foo University", "country": null}],
  "teams": {
    "user_team": {"key": "user_team", "display_name": "Awesome!", "members": ["user"],
                  "category": "participants", "affiliation": "foo"}
  }
}
```

Roles: `participant`, `jury`, `organizer` (admin + jury + team), `admin`.
Passwords are bcrypt hashes (`User.hash_password`), only set on creation unless `--overwrite-passwords` is given.
Every DOMjudge user needs a team to submit; teams reference users, categories and affiliations by key (an unknown key is an error).

`pyjudge make-admin` interactively creates an `admin.json` with one admin user.

## Uploading: `pyjudge upload`

Synchronises files into the database.
All subcommands are idempotent; objects are matched by their key (`externalid` in DOMjudge), so renaming a key creates a new object.

| Command | Effect |
|---------|--------|
| `settings` | Writes `instance.json` settings, creates/updates team categories (categories not listed are deleted) and languages (languages not in the repository are deleted, or disabled if they have submissions) |
| `users FILE [--disable] [--overwrite-passwords]` | Creates/updates affiliations, users, teams. `--disable` disables every user not in the file or whitelist |
| `contest FILE [--force] [--skip-verify] [--skip-problems] [--skip-testcases] [--skip-submissions]` | Creates/updates the contest, then its problems (verification, statement PDF, test cases, jury solutions). Problems no longer listed are removed from the contest, unless teams have submitted to them (DOMjudge would delete those submissions). Refuses to touch a running contest without `--force` |
| `problem (--name KEY \| --regex RE \| --contest FILE)... [--skip-verify] [--skip-testcases] [--skip-submissions]` | Uploads problems without a contest |
| `password KEY` | Asks for a new password of the user with this key and sets it |
| `cleanup` | Deletes submissions with empty or binary source files and submissions without judging |

A failed problem verification stops the upload before the database is touched, with exit code 1.

Jury solutions are uploaded as submissions of synthetic teams: one "Sample Solution <language>" team per language (category `solution`) for accepted solutions, and one "Author <name>" team (category `author`) per matched author.
They are judged like any other submission, which immediately shows whether a problem behaves as expected.

## Exporting: `pyjudge export`

| Command | Effect |
|---------|--------|
| `contest SHORT_NAME [-d FILE]` | Everything about a contest: problems, teams (excluding jury categories), users, submissions with source, verdicts and per-testcase results, clarifications |
| `submissions SHORT_NAME [-d FILE]` | Submissions only |

The contest is selected by its short name (`short_name` in `contest.json`), so the export also works on contests that were not created with pydomjudge.
Output is JSON (`.gz` suffix compresses).
Without `-d`, output goes to stdout only if it is a pipe.
Verdicts use DOMjudge's result strings (see `settings.scoring` above).
The export is the input for `pydomjudge.evaluate` (statistics and plots) and for grading scripts.

`pyjudge anonymize EXPORT [DEST]` replaces logins, names, e-mail addresses and team names of an export by random words and shifts all times by a random offset, for example to share data for teaching or research.
The same export always gives the same result.

## Working with problems: `pyjudge problem`

These commands work on the problem repository only, no database needed.
They share filters: `--name RE`, `--keyword RE`, `--exclude RE` (regular expressions on the folder name or keywords) and `--contest FILE` (all problems of a contest).

| Command | Effect |
|---------|--------|
| `find [filters]` | Lists matching problems with difficulty and keywords |
| `check [filters]` | Verifies problems with `problemtools` (generating test data first) |
| `statements [filters] [DEST] [--language LANG]... [--force]` | Builds the statement PDFs (default language `en`, `--force` rebuilds them), and writes them to a folder, `.zip` or `.tar` |
| `samples [filters] DEST` | Writes sample inputs and answers |
| `seed TEMPLATE --count N [--filename FMT]` | Generates `N` seed files from a Jinja template (variables `n`, `seed`, `random`); see below |

## Problem repository

A repository is a folder with `config.yaml` and `problems/<key>/`, one folder per problem in the [Kattis problem package format](https://www.kattis.com/problem-package-format/) (legacy version, as supported by the vendored `problemtools`).
`--repository PATH` (or `repository` in `pyjudge.yaml`) selects it; otherwise pyjudge looks for `./repository`, then `.` and its parents.

```
repository/
  config.yaml
  compiler/<language>/{build,run}     optional: override the compile scripts shipped with pydomjudge
  checker/<language>/...              optional: override the checker support files (e.g. Java checker framework)
  problems/
    helloworld/
      problem.yaml
      problem_statement/problem.en.tex
      data/sample/*.in *.ans
      data/secret/*.in *.ans | *.seed
      submissions/accepted/*  wrong_answer/*  time_limit_exceeded/*  run_time_error/*
      input_validators/*.ctd            checktestdata grammar (optional, recommended)
      output_validators/<checker>       only for validation: custom
      generators/generator.py           reads a seed file on stdin, writes the input to stdout
```

### `config.yaml`

```yaml
languages: [c, java, python]          # keys from pydomjudge/repository/languages.yml; a mapping overrides settings
affiliations:
  tum: {name: "Technical University of Munich", country: DEU}
authors:
  tobias_meggendorfer:
    name: "Tobias Meggendorfer"
    basic_regex: tobias                # matches file names like pastry_tobias.py (or use `regex` for a full pattern)
    affiliation: tum
```

Jury submissions are attributed to the author whose pattern matches the file name; this decides the "Author" team they are uploaded for.
Each language declares its submission file extensions.

### `problem.yaml`

Besides the Kattis fields, pydomjudge reads:

* `keywords`: list or `-`/`,` separated string.
  Exactly one of `very easy`, `easy`, `medium`, `hard`, `very hard` sets the difficulty shown by `pyjudge problem find`.
* `limits.time_multiplier`: multiplied with `base_time` from `instance.json`.
  A fixed `time_limit` is ignored.
* `limits.memory_limit`, `limits.output_limit` in KiB (optional).
* `validation: custom` with `validator_flags` for problems with a checker in `output_validators/`.
  The checker is a single `.py`, `.c`, `.cpp` or `.java` file, or a folder named after the language.

### Seeded test data

Large inputs are not stored but generated: `data/secret/<name>.seed` holds the generator parameters (lines, `#` comments stripped), `generators/generator.py` (or a single `*Generator.java`) reads them on stdin and prints the input; Python generators run with the interpreter of pydomjudge, so they can use its dependencies (e.g. `numpy`). pydomjudge generates `<name>.in` when the seed or generator is newer, and `<name>.ans` by running the reference solution (a submission named `reference_*`, otherwise the first accepted one).
Generated `.in` files should be ignored in git; `examples/.gitignore` shows the pattern.
Names starting with `tiny_`, `small_`, `medium_`, `large_`, `huge_` are expected to have seeds and determine the test case order in DOMjudge.

`pyjudge problem seed data/secret/small.jinja --count 3` renders a template such as

```
{{ seed }}
5 10
```

into `small_01.seed` to `small_03.seed` in the current directory (run it inside `data/secret`, or pass `--filename` with a path), after asking for confirmation.
Each file gets its own seed, derived from its name, so running it again gives the same files.
The generator must be deterministic.

Each test case may have a `<name>.desc` description and a `<name>.<png|jpg>` image shown in DOMjudge.

## Using the library

The JSON files above are serialised Pydantic models from `pydomjudge.model`.
For anything beyond a one-off setup, write a script that builds `JudgeInstance`, `Contest`, `User`, `Team` and `Affiliation` objects and dumps them with `model_dump_json()`; see `examples/script.py`.
The database layer in `pydomjudge.database` offers the same operations as the CLI as functions taking a cursor, e.g. `create_or_update_users`, for use in your own tooling (the self-service registration is an example).
