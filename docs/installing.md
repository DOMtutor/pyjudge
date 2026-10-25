# Installing

`pydomjudge` is a Python package (Python 3.12 or newer) that depends on [problemtools](https://github.com/Kattis/problemtools), vendored as the git submodule `libs/problemtools`.
Problem verification additionally needs a few system programs.

## System packages

Debian/Ubuntu:

| Purpose | Packages |
|---------|----------|
| build `checktestdata` (input validation) | `automake g++ make libboost-dev libgmp-dev` |
| run jury solutions during verification | `pypy3` (Python), `default-jdk` (Java), `g++` (C++), as needed |
| build problem statements | `texlive-latex-extra texlive-luatex texlive-fonts-recommended texlive-plain-generic ghostscript` |
| run DOMjudge locally | Docker Engine with the Compose plugin, installed as the [Docker documentation](https://docs.docker.com/engine/install/) recommends |

See `libs/problemtools/README.md` for other distributions.

## With uv (recommended)

```shell
git clone --recurse-submodules git@github.com:DOMtutor/pyjudge.git
cd pyjudge
(cd libs/problemtools && make)
uv sync                  # library, CLI tools, web tools, statistics and the dev tools
```

Run commands with `uv run pyjudge ...` or activate the environment (`source .venv/bin/activate`).

If you cloned without `--recurse-submodules`, run `git submodule update --init --recursive`.

## With pip

```shell
python3 -m venv .venv && source .venv/bin/activate
(cd libs/problemtools && make && SETUPTOOLS_SCM_PRETEND_VERSION=0.1 pip install .)
pip install .
```

`pip` does not read `[tool.uv.sources]`, so `problemtools` has to be installed first by hand.

## Installing into another project

Add `pydomjudge` as a dependency of your own project, for example course automation scripts:

```toml
[project]
dependencies = ["pydomjudge"]

[tool.uv.sources]
pydomjudge = { git = "https://github.com/DOMtutor/pyjudge.git" }
problemtools = { git = "https://github.com/DOMtutor/problemtools.git" }
```

## Docker image

The `Dockerfile` builds an image with pydomjudge, `problemtools` and `gunicorn`, intended for running the fuzzer or the self-service.
See [tools.md](tools.md).
