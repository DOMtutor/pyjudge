# pydomjudge

A Python library and command-line toolkit to drive a [DOMjudge](https://www.domjudge.org/) instance from a version-controlled problem repository: problems, test data, jury solutions, contests, users and judge settings are described in files and synchronised into the DOMjudge database.
It is the core of **DOMtutor**, a setup for using DOMjudge in teaching.

> Naming: the GitHub repository is `pyjudge`, the Python package and import name is `pydomjudge`.

## What is in the box

| Component | Where | Purpose |
|-----------|-------|---------|
| Library | `pydomjudge.model`, `pydomjudge.database` | Pydantic models for contests, users, teams, settings; SQL layer that creates or updates them in DOMjudge |
| Problem repository | `pydomjudge.repository` | Reads problems in the [Kattis problem package format](https://www.kattis.com/problem-package-format/) (via `problemtools`), with extensions for seeded test data generation |
| Command line | `pyjudge upload`, `pyjudge export`, `pyjudge problem`, ... | Day-to-day operations, see [docs/usage.md](docs/usage.md) |
| Statistics | `pydomjudge.evaluate` | Aggregate and plot submission data of exported contests |
| Web tools | `pydomjudge.tools` | Fuzzer (find failing inputs for a submission) and self-service (registration, password change) |
| Watcher | `tools/watcher` | Standalone daemon that sends notifications on judgehost outages and new clarifications |

## Quick start

New here?
Follow the [getting started guide](docs/getting-started.md).
It takes you from an empty machine to a locally running DOMjudge with an example contest uploaded.

Short version for people who know DOMjudge and `uv`:

```shell
git clone --recurse-submodules git@github.com:DOMtutor/pyjudge.git && cd pyjudge
(cd libs/problemtools && make)      # builds checktestdata, needs automake g++ libboost-dev libgmp-dev
uv sync
cd examples                         # edit db.yml to match your DOMjudge database
uv run pyjudge upload settings
uv run pyjudge upload users users.json
uv run python script.py --pretty -O contest.json contest   # contest starting in an hour
uv run pyjudge upload contest contest.json
```

## Documentation

* [Getting started](docs/getting-started.md): from zero to a running local setup
* [Installing](docs/installing.md): dependencies and installation variants
* [Usage](docs/usage.md): command-line tools, configuration files, problem repository layout
* [Deployment](docs/deployment.md): running DOMjudge itself with Docker
* [Tools](docs/tools.md): fuzzer, self-service (registration, password change), watcher, Docker image
* [Examples](examples/README.md): a ready-to-use example setup

## Development

```shell
uv sync --all-packages      # including the watcher (a uv workspace member)
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run ty check
```

`pre-commit install` enables the ruff hooks.
CI runs the same steps on every push and pull request.
`tests/integration/run.sh` uploads the examples into a throwaway DOMjudge (Docker) and checks that its jury, team and public pages work with the data; `JUDGE=1` also judges the jury solutions and a hello world per language.
Open points and known issues are collected in [TODO.md](TODO.md) and [docs/review.md](docs/review.md).

## License

GPL-3.0-or-later, see [LICENCE](LICENCE).
The bundled `problemtools` submodule is MIT licensed.
