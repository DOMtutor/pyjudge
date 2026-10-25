"""The only module that uses problemtools.

Everything else (the repository, the fuzzer, the scripts) goes through the
small API here, so a problemtools update can only break this file. Written
against problemtools 0203e29477c9 (the libs/problemtools submodule,
``git describe``: v1.20231016-440-g0203e29).

problemtools internals used here, each marked "problemtools internal" below:

* ``Problem.submissions._submissions``: the programs per verdict directory
* ``Problem.output_validators._validators``: replaced by a custom checker
* ``Problem._check_*`` and the parts' ``check(context)``: verification
  without the statement
* ``argparse.Namespace`` stand-ins for problemtools' command-line arguments
  (``Problem(args=...)``, ``Context(args=...)``, ``problem2pdf.convert``)
* ``TestCase.run_submission_real``: one run of a program on one input
* ``Problem.load()`` loads only once, but copies submissions and validators
  into the temporary directory of the ``with`` block, removed on exit: every
  ``with`` block gets a fresh problemtools ``Problem``

tests/test_problemtools_adapter.py calls every entry point, so that changes of
these internals fail the tests.
"""

import argparse
import logging
import pathlib
import re
from dataclasses import dataclass

import problemtools.run
import problemtools.verifyproblem
from problemtools import languages as _languages

PROBLEMTOOLS_COMMIT = "0203e29477c99f2b89471a640abc3c92b220e6ed"

VerifyError = problemtools.verifyproblem.VerifyError


class Program:
    """A program problemtools compiles and runs (a submission, a checker)."""

    def __init__(self, raw: problemtools.run.Program):
        self._raw = raw

    @property
    def name(self) -> str:
        return self._raw.name  # ty: ignore[unresolved-attribute]  # all subclasses have it

    @property
    def path(self) -> pathlib.Path:
        """Where problemtools copied the program to."""
        return pathlib.Path(self._raw.path)  # ty: ignore[unresolved-attribute]

    def compile(self) -> tuple[bool, str | None]:
        """Success and, on failure, the compiler message."""
        return self._raw.compile()

    def run(
        self, infile: pathlib.Path, outfile: pathlib.Path, errfile: pathlib.Path
    ) -> int:
        """The exit status of a run on infile."""
        status, _ = self._raw.run(
            infile=str(infile), outfile=str(outfile), errfile=str(errfile)
        )
        return status

    def __str__(self) -> str:
        return self.name


def source_program(
    source_directory: pathlib.Path, language_key: str | None, work_dir: pathlib.Path
) -> tuple[Program, str]:
    """The program of the sources in a directory, compiled in work_dir, and the
    name of its language: language_key in problemtools' configuration, or the
    language detected from the file names."""
    config = _languages.load_language_config(pathlib.Path.cwd())
    language = config.languages.get(language_key) if language_key else None
    if language is None:
        language = config.detect_language(
            [str(path) for path in source_directory.iterdir()]
        )
    if language is None:
        raise ValueError("Could not detect the language of the sources")
    program = problemtools.run.SourceCode(
        str(source_directory), language=language, work_dir=str(work_dir)
    )
    return Program(program), language.name


@dataclass(frozen=True)
class RunOutcome:
    """Result of one run: problemtools' verdict (AC, WA, TLE, RTE, JE), the
    runtime (-1 if it did not run) and the validator's feedback files."""

    verdict: str | None
    runtime: float
    additional_info: str | None


class TestGroup:
    """Test data in a directory, as problemtools reads it."""

    def __init__(self, raw: problemtools.verifyproblem.TestCaseGroup):
        self._raw = raw


class LoadedProblem:
    """A problem inside its ``with`` block."""

    def __init__(self, raw: problemtools.verifyproblem.Problem):
        self._raw = raw

    @property
    def tmpdir(self) -> pathlib.Path:
        return pathlib.Path(self._raw.tmpdir)

    def submissions(self) -> dict[str, list[Program]]:
        """The programs in submissions/, by verdict (AC, WA, TLE, ...)."""
        # problemtools internal
        submissions_by_type = self._raw.submissions._submissions
        return {
            verdict: [Program(program) for program in programs]
            for verdict, programs in submissions_by_type.items()
        }

    def use_output_validator(
        self, directory: pathlib.Path, include_dir: pathlib.Path | None
    ) -> None:
        """Replace the output validators by the build/run program in directory."""
        validator = problemtools.run.BuildRun(
            str(directory),
            work_dir=self._raw.tmpdir,
            include_dir=str(include_dir) if include_dir is not None else None,
        )
        # problemtools internal
        self._raw.output_validators._validators = [validator]

    def check(self) -> None:
        """Verify everything but the statement; raises VerifyError (with
        bail_on_error) or logs the problems found."""
        context = problemtools.verifyproblem.Context(
            # problemtools internal: stand-in for its command-line arguments
            args=argparse.Namespace(
                data_filter=re.compile(".*"),
                submission_filter=re.compile(".*"),
                fixed_timelim=None,
            ),
            executor=None,
        )
        p = self._raw
        # problemtools internal: what Problem.check() does, without the statement
        p._check_symlinks()
        p._check_file_and_directory_names()
        p._check_submission_directory_names()
        p.config.check(context)
        p.attachments.check(context)
        p.input_validators.check(context)
        p.output_validators.check(context)
        p.graders.check(context)
        p.testdata.check(context)
        p.submissions.check(context)

    def test_group(self, directory: pathlib.Path) -> TestGroup:
        return TestGroup(
            problemtools.verifyproblem.TestCaseGroup(self._raw, str(directory))
        )

    def run_test_case(
        self,
        group: TestGroup,
        program: Program,
        input_file: pathlib.Path,
        time_limit: float,
        data_filter: str,
    ) -> RunOutcome:
        """Run program on input_file (with its .ans next to it) in group."""
        # problemtools internal: stand-in for its command-line arguments
        args = argparse.Namespace(
            bail_on_error=False,
            werror=False,
            parts=["submissions"],
            problemdir=self._raw.probdir,
            max_additional_info=15,
            data_filter=problemtools.verifyproblem.re_argument(data_filter),
            submission_filter=problemtools.verifyproblem.re_argument(".*"),
            fixed_timelim=None,
        )
        test_case = problemtools.verifyproblem.TestCase(
            self._raw, str(input_file.with_suffix("")), group._raw
        )
        # problemtools internal
        result, _, _ = test_case.run_submission_real(
            program._raw,
            problemtools.verifyproblem.Context(args, None),
            time_limit,
            int(time_limit + 1),
            int(time_limit * 2),
        )
        return RunOutcome(
            verdict=result.verdict,
            runtime=result.runtime,
            additional_info=result.additional_info,
        )


class Problem:
    """problemtools' view of a problem directory; use it in a ``with`` block."""

    def __init__(self, directory: pathlib.Path):
        self.directory = directory
        self._raw: problemtools.verifyproblem.Problem | None = None

    def _new(self) -> problemtools.verifyproblem.Problem:
        return problemtools.verifyproblem.Problem(
            str(self.directory.absolute()),
            # problemtools internal: stand-in for its command-line arguments
            args=argparse.Namespace(
                bail_on_error=True, werror=False, max_additional_info=15
            ),
        )

    def __enter__(self) -> LoadedProblem:
        # A fresh problem per block, see the module documentation
        self._raw = self._new()
        self._raw.__enter__()
        self._raw.load()
        return LoadedProblem(self._raw)

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        assert self._raw is not None
        self._raw.__exit__(exc_type, exc_val, exc_tb)


def check_limit_capabilities(logger: logging.Logger) -> None:
    """Warn if this process cannot set the resource limits of runs."""
    import problemtools.run.limit

    problemtools.run.limit.check_limit_capabilities(logger)


def build_statement_pdf(
    problem_directory: pathlib.Path,
    language: str,
    destination: pathlib.Path,
    quiet: bool = True,
) -> None:
    """Render problem_statement/problem.<language>.tex of problem_directory
    (named like the problem) to destination; LaTeX errors leave no file."""
    import problemtools.problem2pdf

    # problemtools internal: stand-in for its command-line arguments
    options = argparse.Namespace(
        language=language,
        destfile=str(destination.absolute()),
        quiet=quiet,
        nopdf=False,
        problem=str(problem_directory.absolute()),
    )
    problemtools.problem2pdf.convert(options)
