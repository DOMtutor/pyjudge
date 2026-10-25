# Companion Tools

## Fuzzer

Finds failing inputs for a submission on problems with seeded test data.
It repeatedly generates fresh inputs from a chosen seed file, runs the submission and the reference solution, and reports the smallest failing case (for multi-case inputs, it narrows down to the failing case).

```shell
dt_fuzzer --repository path/to/repository
```

Opens a small web UI at <http://127.0.0.1:5000>: choose problem, seed file, language, paste the source, and start.
Only problems with at least one `.seed` file in `data/secret` are offered.
The fuzzer uses `problemtools` to compile and run, so the same system dependencies as for problem verification apply.

## Self-service registration

A one-page Flask app that lets users pick a login name and password.
It creates a DOMjudge user with role `participant` and a one-person team in category `participants`.

```shell
cp src/pydomjudge/tools/selfservice/example_config.yaml config.yaml   # edit database and secret_key
dt_selfservice --config config.yaml
```

Run it behind a reverse proxy with TLS for anything but local tests, and set `server.trust_proxy` so Flask sees the correct scheme and host.

## Watcher

`tools/watcher` is a standalone daemon (own `pyproject.toml`, no dependency on pydomjudge) that polls the DOMjudge API and sends notifications through [Apprise](https://github.com/caronc/apprise) (Telegram, mail, ...) when the server or judgehosts go down or a team posts a clarification.

```shell
cd tools/watcher
cp example_config.yaml config.yaml      # edit judges and notification channels
uv run domjudge_watcher --config config.yaml
```

The API user needs the roles API reader and jury.
State (last seen clarification) is kept in `.watcher_state.json` next to the configuration.

## Docker image

The repository `Dockerfile` builds an image with pydomjudge, `problemtools` and `gunicorn`.
Its entrypoint starts one of the web tools on port 8000:

```shell
docker build -t pyjudge .
docker run --rm -p 8000:8000 -v "$PWD/config.yaml:/app/config.yaml" pyjudge selfservice
docker run --rm -p 8000:8000 -v "$PWD/repository:/repository" pyjudge fuzzer
```

The self-service reads its configuration from `APP_CONFIG_PATH` (default `config.yaml` in the working directory).

The fuzzer runs with a single gunicorn worker, because running fuzzing jobs and their results live in the worker's memory.
The image contains `pypy3` and the `checktestdata` runtime, so it can fuzz Python submissions with Python generators and reference solutions; other languages need an image extended with their compilers (for example `g++` or a JDK).

`tools/watcher/Dockerfile` builds a separate image for the watcher.
