# Compile scripts

One folder per language key of `../languages.yml`.
Each folder is a DOMjudge compile executable: `dt_judge_upload settings` uploads its files, DOMjudge runs `build` once to prepare the executable and then, for every submission, `run program <memory limit KiB> <sources...>` in the directory with the sources (see `judge/compile.sh` of DOMjudge).
A repository can replace a folder with its own `compiler/<language>/`.

## Origin

All scripts except `julia` are DOMjudge 9.0.1's `sql/files/defaultdata` (`c`, `cpp`, `java` = `java_javac_detect` with `DetectMain.java`, `python` = `py3`, `haskell` = `hs`, `javascript` = `js`, `rust` = `rs`, `pascal` = `pas`), with the deviations below, each marked with a `# pydomjudge:` comment.
To update them, copy the new upstream files over these, then re-apply the deviations (`git log -p` of this folder shows them as a diff against upstream).

| Language | Deviation from DOMjudge | Why |
|----------|------------------------|-----|
| c, cpp | `-DDOMJUDGE -DNDEBUG`, `-std=c17` / `-std=gnu++17` | programs can detect the judge; `assert` is off; fixed language standard |
| java | `-DDOMJUDGE` system property | programs can detect the judge |
| python | `pypy3 -O` | `assert` statements are not executed |
| haskell | `-DDOMJUDGE` (with the CPP extension), `-ferror-spans` | programs can detect the judge; clearer errors |
| pascal | `-dDOMJUDGE` | programs can detect the judge |
| rust | `--cfg DOMJUDGE`, `--crate-type bin`, `--edition=2024` (needs rustc 1.85), absolute `TMPDIR`, exit code of `rustc` | upstream always exits 0, so compile errors became run errors |
| julia | written for pydomjudge, same structure as the other interpreted languages | DOMjudge has no Julia script |

`tests/test_compile_scripts.py` runs every script like `compile.sh` does, for each compiler installed on the machine.
All scripts except `julia` were also checked in the chroot of the DOMtutor judgehost image.

## Local verification differs

`dt_kattis_check` and the upload's verification use problemtools, which compiles and runs submissions with its own settings (`problemtools/config/languages.yaml`), not with these scripts.
So a jury solution can pass locally and behave differently on DOMjudge, for example: `DOMJUDGE` is not defined locally, Python asserts are executed locally but not on the judge, and the C/C++ flags differ.

## Open questions for the owner

* `pypy3 -O` (since 2024-12): turning off asserts also affects students' code; intended?
* The DOMtutor judgehost image has no Julia in its chroot, so Julia submissions cannot be judged there.
  Install it in the chroot (domjudge-packaging) or drop `julia` from `languages.yml`?
