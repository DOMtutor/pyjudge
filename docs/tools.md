# Companion Tools

## Fuzzer

Finds failing inputs for a submission on problems with seeded test data.
It repeatedly generates fresh inputs from a chosen seed file, runs the submission and the reference solution, and reports the smallest failing case (for multi-case inputs, it narrows down to the failing case).

```shell
pyjudge serve fuzzer --repository path/to/repository [--base-time 1.5 | --instance instance.json] [--host H --port P]
```

Opens a small web UI at <http://127.0.0.1:5000>: choose problem, seed file, language, paste the source, and start.
Only problems with at least one `.seed` file in `data/secret` are offered, and only the languages of the repository are accepted.
The time limit is the base time (default 1 s, or `base_time` of the given `instance.json`) times the problem's `time_multiplier`, as in DOMjudge.
The fuzzer uses `problemtools` to compile and run, so the same system dependencies as for problem verification apply.

The fuzzer compiles and runs whatever is submitted, without a sandbox: only make it reachable for people you trust.
Under a WSGI server, use `pydomjudge.tools.fuzzer:create_app()` with exactly one worker process (running jobs live in its memory), configured by the environment variables `PYJUDGE_REPOSITORY` and `PYJUDGE_BASE_TIME`.

## Self-service

A small Flask app with two services, each enabled in the required `services:` section of the configuration (at least one):

* `register` (`/register`): users pick a login name and password.
  It creates a DOMjudge user with role `participant` and a one-person team in the category with key `category` (default `participants`; the app refuses to start if it does not exist).
  Login names follow DOMjudge's rules (letters, digits and `_-@.`, here at most 64 characters) and, if set, must match `username_pattern`.
  A name that is already used as login or key of a user, or as name or key of a team, is rejected; existing users are never modified.
* `change_password` (`/password`): users change their password with their current one.
  Only enabled users whose only role is `team` can; every refusal (unknown user, wrong password, other roles) gets the same answer.
  Failed attempts are limited per login name and address (`attempts`, default 5) and per address (`address_attempts`, default 30) within `window_seconds` (default 900).
  Existing DOMjudge sessions stay valid.

With one service enabled, `/` redirects to it; otherwise it lists the enabled ones.
Disabled services answer 404. The database password and the secret key can come from environment variables (`password_env`, `secret_key_env`), as in `pyjudge.yaml`.

```shell
cp src/pydomjudge/tools/selfservice/example_config.yaml config.yaml   # edit database and secret_key
pyjudge serve selfservice --config config.yaml
```

Run it behind a reverse proxy with TLS for anything but local tests, and set `server.trust_proxy` so Flask sees the correct scheme, host and client address (used by the attempt limit).
Under a WSGI server, use `pydomjudge.tools.selfservice:create_app()` with a single worker process, since the attempt limit is kept in memory.

`pyjudge upload users --overwrite-passwords` sets the passwords of `users.json` again, also for users who changed theirs here.

## Watcher

`tools/watcher` is a standalone daemon (own `pyproject.toml`, no dependency on pydomjudge) that polls the DOMjudge API and sends notifications through [Apprise](https://github.com/caronc/apprise) (Telegram, mail, ...) when the server or judgehosts go down or a team posts a clarification.
It is a member of the repository's uv workspace and shares its lock file.

```shell
cp tools/watcher/example_config.yaml config.yaml     # edit judges and notification channels
uv run --package domjudge_watcher domjudge_watcher --config config.yaml
```

The API user needs the roles API reader and jury.
State (last seen clarification) is kept in `.watcher_state.json` next to the configuration.

## Docker image

The repository `Dockerfile` builds an image with pydomjudge, `problemtools` and `gunicorn`.
Its entrypoint starts one of the web tools on port 8000:

```shell
docker build -t pyjudge .
docker run --rm -p 8000:8000 -v "$PWD/config.yaml:/app/config.yaml" pyjudge selfservice
docker run --rm -p 8000:8000 -v "$PWD/repository:/repository" pyjudge fuzzer   # PYJUDGE_REPOSITORY=/repository
```

The self-service reads its configuration from `APP_CONFIG_PATH` (default `config.yaml` in the working directory) and also runs with a single worker.

The fuzzer runs with a single gunicorn worker, because running fuzzing jobs and their results live in the worker's memory.
The image contains `pypy3` and the `checktestdata` runtime, so it can fuzz Python submissions with Python generators and reference solutions; other languages need an image extended with their compilers (for example `g++` or a JDK).

`tools/watcher/Dockerfile` builds a separate image for the watcher.
