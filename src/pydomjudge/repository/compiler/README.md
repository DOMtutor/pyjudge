# Compile scripts

One folder per language key of `../languages.yml`.
Each folder is a DOMjudge compile executable: `pyjudge upload settings` uploads its files, DOMjudge runs `build` once to prepare the executable and then, for every submission, `run program <memory limit KiB> <sources...>` in the directory with the sources (see `judge/compile.sh` of DOMjudge).
A repository can replace a folder with its own `compiler/<language>/`.

## Origin

All scripts are DOMjudge 9.0.1's `sql/files/defaultdata` (`c`, `cpp`, `java` = `java_javac_detect` with `DetectMain.java`, `python` = `py3`, `haskell` = `hs`, `javascript` = `js`, `rust` = `rs`, `pascal` = `pas`), with the deviations below, each marked with a `# pydomjudge:` comment.
To update them, copy the new upstream files over these, then re-apply the deviations (`git log -p` of this folder shows them as a diff against upstream).

| Language | Deviation from DOMjudge | Why |
|----------|------------------------|-----|
| c, cpp | `-DDOMJUDGE -DNDEBUG`, `-std=c17` / `-std=gnu++17` | programs can detect the judge; `assert` is off; fixed language standard |
| java | `-DDOMJUDGE` system property | programs can detect the judge |
| python | `pypy3 -O` | `assert` statements are not executed (intended, like `-DNDEBUG` for C/C++) |
| haskell | `-DDOMJUDGE` (with the CPP extension), `-ferror-spans` | programs can detect the judge; clearer errors |
| pascal | `-dDOMJUDGE` | programs can detect the judge |
| rust | `--cfg DOMJUDGE`, `--crate-type bin`, `--edition=2024` (needs rustc 1.85), absolute `TMPDIR`, exit code of `rustc` | upstream always exits 0, so compile errors became run errors |

`tests/test_compile_scripts.py` runs every script like `compile.sh` does, for each compiler installed on the machine.
All scripts were also checked in the chroot of the DOMtutor judgehost image.

## Local verification differs

`pyjudge problem check` and the upload's verification use problemtools, which compiles and runs submissions with its own settings (`problemtools/config/languages.yaml`), not with these scripts.
So a jury solution can pass locally and behave differently on DOMjudge, for example: `DOMJUDGE` is not defined locally, Python asserts are executed locally but not on the judge, and the C/C++ flags differ.

