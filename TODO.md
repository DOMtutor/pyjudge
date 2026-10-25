# TODOs

In order of priority.
Sizes are rough estimates.

1. **`--dry-run` for `pyjudge upload`** (about 1-2 days): the writer upserts everything (an unchanged second upload runs 83 statements that change no rows), so a dry run has to compare with the database instead of logging statements.
   Also a change summary at the end of every upload.
2. **`pyjudge doctor`** (half a day): check checktestdata, pypy3, LaTeX, compilers and the database connection, with install hints.
3. **Progress output** during verification and statement builds (problem, step, duration).
4. **Integration tests with the DOMtutor images** and more languages through the judgehost (only c, java and python of the example repository are judged now).
5. **Self-service**: registration restricted to a roster or invitation codes (`username_pattern` covers simple cases), optional e-mail field.
6. **Long term**: replace problemtools (all of it is behind `pydomjudge.repository._problemtools`).
