# TODOs

In order of priority.
Sizes are rough estimates.

1. **Course framework, first step** (about 2-3 days): `pyjudge course ...` commands for what LZSCC.111 and LZSCC.223 both do: a course file (contests, problems, lecturers), users and passwords from a Moodle export (generated passwords from a word list, a distribution CSV instead of bcrypt hashes in `users.json`), and a grades CSV (best verdict per team and problem).
   Their scripts use APIs that no longer exist; decide first which of the two diverged copies is the reference.
2. **Course framework, grading** (about 2 days, separate optional package or extra): plagiarism (copydetect, text similarity), OCR of PDF submissions, feedback documents.
   Heavy dependencies (tesseract, poppler, python-docx).
3. **Problem set and solution PDFs with Jinja templates** (about 1-1.5 days, with item 1): one rendering path for the course problem sets and the single statements, which problemtools' `problem2pdf` renders today.
   Statement PDFs must stay byte-identical between builds (`SOURCE_DATE_EPOCH`), or every upload replaces them.
   Includes the referenced files of solutions: files next to `solution/solution.tex` are linked flat into one build directory, so equal names in two problems would collide (none do yet); give each problem its own directory or graphics path.
4. **`--dry-run` for `pyjudge upload`** (about 1-2 days): the writer upserts everything (an unchanged second upload runs 83 statements that change no rows), so a dry run has to compare with the database instead of logging statements.
   Also a change summary at the end of every upload.
5. **`pyjudge doctor`** (half a day): check checktestdata, pypy3, LaTeX, compilers and the database connection, with install hints.
6. **Progress output** during verification and statement builds (problem, step, duration).
7. **Integration tests with the DOMtutor images** and more languages through the judgehost (only c, java and python of the example repository are judged now).
8. **Self-service**: registration restricted to a roster or invitation codes (`username_pattern` covers simple cases), optional e-mail field.
9. **Long term**: replace problemtools (all of it is behind `pydomjudge.repository._problemtools`).
