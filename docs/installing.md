# Initial Setup for DOMtutor

* Clone `pyjudge` into some directory.
* In this directory, run `git submodule update --init --recursive` to check out the `problemtools` repository
* Create a virtual environment with `python3 -m venv venv` and activate it with `. ./venv/bin/activate` (or use `uv venv`)
* `cd problemtools` and `make` to compile `checktestdata` (may need `build-essentials`, `automake`, `libboost-dev`, `libgmp-dev`)
* Install `pyjudge` in the venv by `cd pyjudge && pip install .` (or `uv pip install .`)
* To build problems you may also need `texlive-latex-extra poppler-utils` (or your distribution's equivalent)
