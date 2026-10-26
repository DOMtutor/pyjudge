# Compile scripts

One folder per language key of `../languages.yml`.
Each folder is a DOMjudge compile executable: `pyjudge upload settings` uploads its files, DOMjudge runs `build` once to prepare the executable and then, for every submission, `run program <memory limit KiB> <sources...>` in the directory with the sources (see `judge/compile.sh` of DOMjudge).
A repository can replace a folder with its own `compiler/<language>/`.

## What problem authors should know

- `DOMJUDGE` is defined at compile time: `-DDOMJUDGE` for C, C++ and Haskell (with the CPP extension), `-dDOMJUDGE` for Pascal, `--cfg DOMJUDGE` for Rust; Java programs run with the system property `DOMJUDGE` set.
  At run time, every submission sees `DOMJUDGE=1` in its environment through pydomjudge's run script (see [docs/usage.md](../../../../docs/usage.md#run-script)).
- Assertions are off: `-DNDEBUG` for C and C++, `pypy3 -O` for Python.
- The language standards are fixed: C17 (`-std=c17`), C++17 (`-std=gnu++17`) and Rust edition 2024 (needs rustc 1.85).
- A Rust compile error is a compile error (the script exits with rustc's exit code).

`tests/test_compile_scripts.py` runs every script like DOMjudge's `compile.sh` does, for each compiler installed on the machine.

## Local verification differs

`pyjudge problem check` and the upload's verification use problemtools, which compiles and runs submissions with its own settings (`problemtools/config/languages.yaml`), not with these scripts.
So a jury solution can pass locally and behave differently on DOMjudge, for example: `DOMJUDGE` is not defined locally, Python asserts are executed locally but not on the judge, and the C/C++ flags differ.

