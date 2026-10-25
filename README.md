# pydomjudge

A Python library and command-line toolkit to drive a [DOMjudge](https://www.domjudge.org/) instance from a version-controlled problem repository: problems, test data, jury solutions, contests, users and judge settings are described in files and synchronised into the DOMjudge database.
It is the core of **DOMtutor**, a setup for using DOMjudge in teaching.

> Naming: the GitHub repository is `pyjudge`, the Python package and import name is `pydomjudge`.

## What is in the box

| Component | Where | Purpose |
|-----------|-------|---------|
| Library | `pydomjudge.model`, `pydomjudge.database` | Pydantic models for contests, users, teams, settings; SQL layer that creates or updates them in DOMjudge |
| Problem repository | `pydomjudge.repository` | Reads problems in the [Kattis problem package format](https://www.kattis.com/problem-package-format/) (via `problemtools`), with extensions for seeded test data generation |
| CLI tools | `dt_judge_upload`, `dt_judge_export`, `dt_kattis_*`, ... | Day-to-day operations, see [docs/usage.md](docs/usage.md) |
| Statistics | `pydomjudge.evaluate` | Aggregate and plot submission data of exported contests |
| Web tools | `pydomjudge.tools` | Fuzzer (find failing inputs for a submission) and self-service registration |
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
uv run dt_judge_upload settings
uv run dt_judge_upload users users.json
uv run python script.py --pretty -O contest.json contest   # contest starting in an hour
uv run dt_judge_upload contest contest.json
```

## Documentation

* [Getting started](docs/getting-started.md): from zero to a running local setup
* [Installing](docs/installing.md): dependencies and installation variants
* [Usage](docs/usage.md): command-line tools, configuration files, problem repository layout
* [Deployment](docs/deployment.md): running DOMjudge itself with Docker
* [Tools](docs/tools.md): fuzzer, self-service registration, watcher, Docker image
* [Examples](examples/README.md): ready-to-use example setups

## Development

```shell
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run ty check
```

`pre-commit install` enables the ruff hooks.
CI runs the same steps on every push and pull request.
Open points and known issues are collected in [TODO.md](TODO.md) and [docs/review.md](docs/review.md).

## License

GPL-3.0-or-later, see [LICENCE](LICENCE).
The bundled `problemtools` submodule is MIT licensed.
