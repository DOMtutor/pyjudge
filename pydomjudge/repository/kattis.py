import argparse
import dataclasses
import filecmp
import logging
import mimetypes
import pathlib
import re
import shutil
import stat
import subprocess
import tempfile
import importlib.resources as res
from importlib.abc import Traversable
from typing import Optional, List, Dict, Tuple, Collection, Any, Mapping, Callable

import yaml

from pydomjudge.util import link_or_copy
from pydomjudge.model.language import FileData

import problemtools.run as run
import problemtools.verifyproblem
import problemtools.verifyproblem as verify
from pydomjudge.model import (
    ProblemTestCase,
    Affiliation,
    JuryProblemSubmission,
    Verdict,
    Language,
    Problem,
    ProblemLimits,
    Executable,
    ProblemLoader,
    ExecutableType,
    Team,
)
from pydomjudge.model.team import SystemCategory
from pydomjudge.model.util import get_md5

from problemtools.run import BuildRun
from pydomjudge.util import rasterize_pdf

log = logging.getLogger(__name__)


class ExecutionError(Exception):
    def __init__(self, err):
        self.err = err

    def __str__(self):
        return f"{self.err}"


class StatusExecutionError(ExecutionError):
    def __init__(self, code, out, err, details=None):
        super().__init__(err)
        self.code = code
        self.out = out
        self.details = details

    def __str__(self):
        return f"Exit with {self.code}{f' {self.details}' if self.details else ''}\n{self.out}\n{self.err}"


class KattisRepositoryError(Exception):
    pass


class RepositoryTestCase(ProblemTestCase):
    def __init__(self, base_path: pathlib.Path):
        self.base_path = base_path
        self.input_file = base_path.with_suffix(".in")
        self.output_file = base_path.with_suffix(".ans")
        assert self.input_file.is_file() and self.output_file.is_file()

        self._image_path = None
        self._image_extension = None
        for sibling in base_path.parent.glob(f"{base_path.name}.*"):
            (mimetype, _) = mimetypes.guess_type(sibling)
            if mimetype and mimetype.startswith("image/"):
                if self._image_path is not None:
                    log.warning("Found multiple images for submission %s", self)
                else:
                    extension = mimetypes.guess_extension(mimetype)
                    if extension is None:
                        log.warning(
                            "Could not find extension for mimetype %s", mimetype
                        )
                    else:
                        self._image_path = sibling
                        self._image_extension = extension[1:]

    @property
    def input(self):
        with open(self.input_file, mode="rb") as f:
            return f.read()

    @property
    def output(self):
        with open(self.output_file, mode="rb") as f:
            return f.read()

    def is_sample(self):
        return self.input_file.parent.name == "sample"

    @property
    def unique_name(self):
        return f"{self.input_file.parent.name}/{self.input_file.name[:-3]}"

    def _load_image(self) -> Optional[bytes]:
        if not self._image_path:
            return None
        with self._image_path.open(mode="rb") as f:
            return f.read()

    @property
    def image_extension(self) -> str:
        return self._image_extension

    @property
    def description(self) -> Optional[str]:
        description_file = self.base_path.with_suffix(".desc")
        if description_file.is_file():
            with description_file.open(mode="rt") as f:
                return f.read()
        return None


@dataclasses.dataclass
class RepositoryAuthor(object):
    key: str
    name: str
    patterns: List[re.Pattern]
    affiliation: Optional[Affiliation]

    @staticmethod
    def parse(key, data, affiliations: Dict[str, Affiliation]):
        if "regex" in data:
            regexes = data["regex"]
            if isinstance(regexes, str):
                regexes = [regexes]
            patterns = [re.compile(regex) for regex in regexes]
        else:
            regexes = data["basic_regex"]
            if isinstance(regexes, str):
                regexes = [regexes]
            patterns = [
                re.compile(rf"^[a-zA-z\d_-]*{regex}[a-zA-z\d_-]*$") for regex in regexes
            ]
        return RepositoryAuthor(
            key=key,
            name=data["name"],
            patterns=patterns,
            affiliation=affiliations[data["affiliation"]]
            if "affiliation" in data
            else None,
        )


class JurySubmission(JuryProblemSubmission):
    EXPECTED_RESULTS = {
        "accepted": [Verdict.CORRECT],
        "too_slow": [Verdict.TIME_LIMIT],
        "time_limit_exceeded": [Verdict.TIME_LIMIT],
        "timelimit_exceeded": [Verdict.TIME_LIMIT],
        "slow_input": [Verdict.CORRECT, Verdict.TIME_LIMIT],
        "slow": [Verdict.CORRECT, Verdict.TIME_LIMIT],
        "run_time_error": [Verdict.RUN_ERROR],
        "runtime_error": [Verdict.RUN_ERROR],
        "wrong_answer": [Verdict.WRONG_ANSWER],
        "compile_error": [Verdict.COMPILER_ERROR],
    }

    def __init__(self, path: pathlib.Path, config: "Repository"):
        assert path.is_file()
        self.path: pathlib.Path = path
        self.config = config
        self._extension = path.suffix
        if self._extension and self._extension[0] == ".":
            self._extension = self._extension[1:]
        self._source_md5 = None

    @property
    def name(self) -> str:
        return self.path.stem.lower()

    @property
    def file_name(self) -> str:
        return self.path.name

    @property
    def extension(self) -> str:
        return self._extension

    @property
    def problem_unique_name(self) -> str:
        return f"{self.category}/{self.name}.{self.extension}"

    @property
    def category(self) -> str:
        return self.path.parent.name

    @property
    def expected_results(self) -> Collection[Verdict]:
        return JurySubmission.EXPECTED_RESULTS[self.category]

    @property
    def language(self) -> Optional[Language]:
        return self.config.find_language_of_submission(self)

    @property
    def author(self) -> Optional[RepositoryAuthor]:
        return self.config.find_author_of(self)

    @property
    def source(self):
        with self.path.open(mode="rb") as f:
            source_bytes: bytes = f.read()
        source_md5 = get_md5(source_bytes)
        if self._source_md5 is None:
            self._source_md5 = source_md5
        elif self._source_md5 != source_md5:
            raise ValueError("Source MD5 changed")
        try:
            source_code: str = source_bytes.decode(encoding="utf-8", errors="strict")
        except UnicodeDecodeError as e:
            raise ValueError(f"Failed to decode {self.path}", e)
        if "\x00" in source_code:
            raise ValueError("NUL string in source code")
        return source_code

    def source_md5(self) -> str:
        if self._source_md5 is None:
            self._source_md5 = get_md5(self.path)
        return self._source_md5

    def __str__(self):
        return f"Submission {self.file_name}@{self.language} ({','.join(map(str, self.expected_results))})"


class RepositoryProblem(Problem):
    UNKNOWN_DIFFICULTY = "unknown"
    DIFFICULTIES = ["very easy", "easy", "medium", "hard", "very hard", "unknown"]

    @staticmethod
    def link_or_copy_problem_statement(
        problem: "RepositoryProblem", destination: pathlib.Path, force=False
    ):

        problem_paths = ["problem_statement", "data/sample", "problem.yaml"]

        repository_path = problem.directory
        for sub_path in problem_paths:
            link_or_copy(
                repository_path / sub_path,
                destination / sub_path,
                force,
            )

    def __init__(self, directory: pathlib.Path, repository: "Repository"):
        self.repository = repository
        self.repository_key: str = directory.name
        self.directory = directory
        description_file = self.directory / "problem.yaml"
        if not description_file.is_file():
            raise ValueError(
                f"Problem {self.repository_key} not found at {description_file}"
            )
        with description_file.open(mode="rt", encoding="utf-8") as f:
            self.description = yaml.safe_load(f)

        self._name = self.description["name"]
        if self.description and "keywords" in self.description:
            k = self.description["keywords"]
            if isinstance(k, list):
                keywords = k
            else:
                keywords = re.split(" - |,", k)
            self.keywords = list(
                [x.strip().lower() for x in keywords]
            )  # replace("-", " ")?
        else:
            self.keywords = []

        difficulty = None
        for keyword in self.keywords:
            if keyword in RepositoryProblem.DIFFICULTIES:
                if difficulty is not None:
                    raise ValueError(
                        f"Found difficulties {difficulty} and {keyword} for problem {self.repository_key}"
                    )
                difficulty = keyword
        if difficulty is None:
            difficulty = RepositoryProblem.UNKNOWN_DIFFICULTY
        self.difficulty = difficulty

        self._validator_flags = self.description.get("validator_flags", None)
        self.validation = self.description.get("validation")

        limits = self.description.get("limits", {})
        time_factor = limits.get("time_multiplier", 1.0)
        if time_factor <= 0.0:
            raise ValueError(
                f"Invalid time factor {time_factor} on problem {self.repository_key}"
            )
        self._limits = ProblemLimits(
            time_factor=time_factor,
            memory_kib=limits.get("memory_limit", None),
            output_kib=limits.get("output_limit", None),
        )

        self._test_cases = None
        self._submissions = None
        self._generator = None
        self._args = argparse.Namespace(
            # might need attributes later?
            # some attributes include:
            # threads: int
            # parts: list[str] ?
            bail_on_error=False,
            werror=False,
            max_additional_info=15
        )
        # self._args added as the second param
        self._problemtools = verify.Problem(str(self.directory.absolute()), self._args)
        self._problemtools_loaded = False
        self._reference_submission = None
        self.log = log.getChild(self.repository_key)

        if "time_limit" in limits:
            self.log.warning("Fixed time limit specified, ignoring")

    @property
    def name(self) -> str:
        return self._name

    @property
    def type(self) -> int:
        # Defaults to 1, which is pass-fail type
        return self.description.get("type", 1)

    @property
    def limits(self) -> ProblemLimits:
        return self._limits

    def __enter__(self) -> problemtools.verifyproblem.Problem:
        p = self._problemtools.__enter__()

        # Call load() for submissions to access submission data
        self._problemtools.load()

        self._validator_temporary_directory = None
        if self.validation == "custom":
            # Add the checkers support data as include directory
            checker_language, checker_directory = Repository.get_checker_data_of(self)
            checker_directory: pathlib.Path

            repository_directory = (
                self.repository.base_directory / "checker" / checker_language
            )
            if repository_directory.exists():
                include_dir = repository_directory
            else:
                default_directory = res.files(
                    f"pydomjudge.repository.checker.{checker_language}"
                )
                if default_directory.is_dir():
                    include_dir = pathlib.Path(
                        tempfile.mkdtemp(prefix=f"pyjudge_checker_{checker_language}")
                    )

                    def action(traversable: Traversable, components: Collection[str]):
                        path = include_dir / pathlib.Path(*components)
                        path.parent.mkdir(exist_ok=True, parents=True)
                        with traversable.open("rb") as f_i:
                            with path.open("wb") as f_o:
                                shutil.copyfileobj(f_i, f_o)
                        if path.name in {"build", "run"}:
                            path.chmod(path.stat().st_mode | stat.S_IEXEC)

                    recurse_traversable(default_directory, action)
                    self._validator_temporary_directory = include_dir
                else:
                    include_dir = None

            # noinspection PyTestUnpassedFixture
            validator = BuildRun(
                str(checker_directory), work_dir=p.tmpdir, include_dir=include_dir
            )
            p.output_validators._validators = [validator]

        reference_submission: run.SourceCode | None = None
        # noinspection PyProtectedMember
        submissions_by_type = self._problemtools.submissions._submissions
        for submissions in submissions_by_type.values():
            for submission in submissions:
                submission: run.SourceCode
                if (
                    submission.name.startswith("reference_")
                    or "_reference_" in submission.name
                ):
                    if reference_submission is None:
                        reference_submission = submission
                    else:
                        self.log.warning("Multiple reference submissions for %s", self)
                        break

        if reference_submission is None:
            for candidate in ["AC", "SL", "TLE"]:
                if candidate in submissions_by_type and submissions_by_type[candidate]:
                    reference_submission = submissions_by_type[candidate][0]
                    break
        self._reference_submission = reference_submission

        self._problemtools_loaded = True
        return p

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._problemtools_loaded = False
        if self._validator_temporary_directory is not None:
            shutil.rmtree(self._validator_temporary_directory)

        self._problemtools.__exit__(exc_type, exc_val, exc_tb)

    @property
    def kattis_problem(self) -> problemtools.verifyproblem.Problem:
        return self._problemtools

    def check(self, force=False):
        last_verified = self.directory / ".last_verified"
        if last_verified.exists() and not force:
            date = last_verified.stat().st_mtime
            if all(
                f.stat().st_mtime <= date
                for f in self.directory.rglob("**/*")
                if f.is_file()
            ):
                self.log.debug("Skipping verification of already checked problem")
                return
            last_verified.unlink()

        self._load_testcases()

        import problemtools.run.limit as limit

        limit.check_limit_capabilities(self)

        verify.ProblemAspect.bail_on_error = True
        with self as p:
            self._generate_testcases()

            p.config.check(None)
            p.attachments.check(None)
            # input_format_validators is outdated
            p.input_validators.check(None)
            p.output_validators.check(None)
            p.graders.check(None)

            args = argparse.Namespace(
                data_filter=re.compile('.*'),
                submission_filter=re.compile('.*'),
                fixed_timelim=None
            )
            context = verify.Context(args, None)
            p.testdata.check(context)
            p.submissions.check(context)

    @property
    def checker_flags(self) -> Optional[str]:
        return self._validator_flags

    @property
    def key(self) -> str:
        return self.repository_key

    @property
    def checker(self) -> Optional[Executable]:
        return self.repository.get_checker_of(self)

    def generate_problem_text_if_required(self, lang="en", force=False):
        import problemtools.problem2pdf

        source_file = self.directory / "problem_statement" / f"problem.{lang}.tex"
        if not source_file.exists():
            raise ValueError(
                f"Problem {self.name} does not have a statement in language {lang}"
            )
        destination_pdf = self.directory / "build" / f"problem.{lang}.pdf"

        regenerate = force or not destination_pdf.exists()
        if not regenerate:
            # TODO Check for every file in sample folder as well as all files in problem_statement
            pdf_mtime = destination_pdf.stat().st_mtime
            regenerate = pdf_mtime < source_file.stat().st_mtime
            if not regenerate:
                for case in self.testcases:
                    if not case.is_sample():
                        continue
                    if (
                        pdf_mtime < case.input_file.stat().st_mtime
                        or pdf_mtime < case.output_file.stat().st_mtime
                    ):
                        regenerate = True
                        break

        if regenerate:
            destination_pdf.parent.mkdir(exist_ok=True, parents=True)

            with tempfile.TemporaryDirectory(prefix=f"dt-{self.repository_key}-") as t:
                directory = pathlib.Path(t)
                problem_directory = directory / self.repository_key
                RepositoryProblem.link_or_copy_problem_statement(
                    self, problem_directory
                )
                build_pdf = problem_directory / f"{self.repository_key}.build.pdf"

                self.log.info("Building problem pdf for language %s", lang)
                options = argparse.Namespace(
                    language=lang,
                    destfile=str(build_pdf.absolute()),
                    quiet=not log.isEnabledFor(logging.DEBUG),
                    nopdf=False,
                    problem=str(problem_directory.absolute()),
                )

                problemtools.problem2pdf.convert(options)

                # TODO Wait till problemtools allows extracting the output
                if not build_pdf.exists():
                    raise ValueError(
                        f"Missing problem pdf for {self.name} -- probably a LaTeX error"
                    )
                rasterize = False
                if rasterize:
                    final_pdf = directory / f"{self.name}.final.pdf"
                    rasterize_pdf(build_pdf, final_pdf)
                    shutil.copy(final_pdf, destination_pdf)
                else:
                    shutil.copy(build_pdf, destination_pdf)
        return destination_pdf

    def problem_text(self, lang="en") -> Tuple[bytes, str]:
        problem_pdf = self.generate_problem_text_if_required(lang)
        with problem_pdf.open(mode="rb") as f:
            return f.read(), "pdf"

    def _find_generator_process(self):
        generator_dir = self.directory / "generators"

        python_files = list(generator_dir.glob("*.py"))
        python_generator: Optional[pathlib.Path] = None
        if len(python_files) == 1:
            python_generator = python_files[0]
        else:
            for file in python_files:
                if file.stem.lower() in {"generator", "generate"}:
                    if python_generator is not None:
                        raise ValueError("Multiple python generators")
                    python_generator = file

        if python_generator is not None:
            logging.debug("Using python generator %s", python_generator.name)
            return python_generator.stat().st_mtime, ["python", python_generator]

        java_files = list(generator_dir.glob("*.java"))
        generators = [file for file in java_files if file.stem.endswith("Generator")]
        if len(generators) > 1:
            raise ValueError("Multiple *Generator.java files")

        if not generators:
            raise ValueError("No generators found")

        generator_classes = [file.name for file in java_files]
        self.log.debug("Compiling generator files %s", " ".join(generator_classes))
        subprocess.run(
            ["javac"] + generator_classes,
            cwd=generator_dir.absolute(),
            timeout=30,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        generator_name = generators[0].with_suffix("").name
        change_time = max(file.stat().st_mtime for file in java_files)

        return change_time, ["java", generator_name]

    def generate_input_if_required(self, seed, input_=None):
        try:
            generator_dir = self.directory / "generators"
            generator_change_time, generator = self._find_generator_process()

            def generate(
                s, seed_file: pathlib.Path, input_file: Optional[pathlib.Path] = None
            ):
                if input_file is None:
                    input_file = seed_file.with_suffix(".in")
                if input_file.exists():
                    in_stat = input_file.stat()
                    seed_change_time = seed_file.stat().st_mtime
                    input_change_time = in_stat.st_mtime
                    if (
                        in_stat.st_size > 0
                        and generator_change_time <= input_change_time
                        and seed_change_time <= input_change_time
                    ):
                        return

                lines = []
                with seed_file.open(mode="rt") as f:
                    for line in f:
                        index = line.find("#")
                        if index >= 0:
                            line = line[:index]
                        line = line.strip()
                        if line:
                            lines.append(line)

                s.log.debug(
                    "Generating input %s from seed file %s",
                    input_file.name,
                    seed_file.name,
                )

                def run_generator(output):
                    return subprocess.run(
                        generator,
                        cwd=generator_dir.absolute(),
                        timeout=20,
                        check=True,
                        input="\n".join(lines),
                        stdout=output,
                        stderr=subprocess.PIPE,
                        text=True,
                    )

                try:
                    with input_file.open(mode="wt") as f:
                        run_generator(f)

                    with tempfile.NamedTemporaryFile(mode="r+t") as t:
                        run_generator(t)

                        if not filecmp.cmp(
                            input_file, pathlib.Path(t.name), shallow=False
                        ):
                            raise ExecutionError(
                                f"Generator produces different outputs for seed {seed_file.name}"
                            )

                except subprocess.CalledProcessError as exc:
                    raise ExecutionError(
                        f"Generator process failed on {seed_file.name}:\n{exc.stderr}"
                    ) from exc

        except ValueError as e:
            message = str(e)
            error = e

            def generate(s, _, __):
                raise ValueError(f"Generator error for {s}: {message}", error)

        # noinspection PyAttributeOutsideInit
        self.generate_input_if_required = generate.__get__(self, RepositoryProblem)
        self.generate_input_if_required(seed, input_)

    def generate_answer_if_required(
        self, input_file: pathlib.Path, answer_file: Optional[pathlib.Path] = None
    ):
        if answer_file is None:
            answer_file = input_file.with_suffix(".ans")

        if answer_file.is_file():
            answer_mtime = answer_file.stat().st_mtime
            input_mtime = input_file.stat().st_mtime

            if answer_mtime >= input_mtime or input_file.parent.name == "sample":
                return
            self.log.debug(
                "Need to re-generate answer %s for %s, since input was recently changed (%s < %s)",
                answer_file.name,
                input_file.name,
                answer_mtime,
                input_mtime,
            )

        if self._reference_submission is None:
            raise KattisRepositoryError(
                f"No correct solution found for problem {self} to generate answers"
            )

        assert self._problemtools_loaded

        self.log.debug(
            "Generating answer for %s using submission %s",
            answer_file.name,
            self._reference_submission.name,
        )

        result, error = self._reference_submission.compile()
        if not result:
            raise ExecutionError(error)

        # noinspection PyTestUnpassedFixture
        error_file = pathlib.Path(self._problemtools.tmpdir) / "submission_ans_error"
        status, _ = self._reference_submission.run(
            infile=str(input_file), outfile=str(answer_file), errfile=str(error_file)
        )
        flag = ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        answer_file.chmod(answer_file.stat().st_mode & flag)
        if status:
            answer_file.unlink(missing_ok=True)
            error = ""
            if error_file.exists():
                with error_file.open(mode="rb") as f:
                    error = f.read().decode("utf-8", "replace")
                error_file.unlink(missing_ok=True)
            raise StatusExecutionError(
                status,
                "",
                error,
                details=f"{self._reference_submission.name} on {input_file.name}",
            )

    def _load_testcases(self) -> Collection[RepositoryTestCase]:
        if self._test_cases is None:
            self._test_cases = []

        for category_directory in (self.directory / "data").iterdir():
            if not category_directory.is_dir():
                continue
            for seed_file in category_directory.glob("*.seed"):
                self.generate_input_if_required(seed_file)

            for input_file in category_directory.glob("*.in"):
                if not input_file.is_file():
                    continue
                if (
                    any(
                        input_file.name.startswith(s)
                        for s in [
                            "small_",
                            "medium_",
                            "large_",
                            "huge_",
                            "tiny_",
                        ]
                    )
                    and not input_file.with_suffix(".seed").exists()
                ):
                    log.warning(
                        "Input file %s has reserved name but no matching seed file",
                        input_file,
                    )

                answer_file = input_file.with_suffix(".ans")
                self.generate_answer_if_required(input_file, answer_file)
                if not answer_file.stat().st_size:
                    answer_file.unlink(missing_ok=True)
                    continue
                self._test_cases.append(
                    RepositoryTestCase(category_directory / input_file.stem)
                )

        return self._test_cases

    @property
    def testcases(self) -> Collection[RepositoryTestCase]:
        return self._load_testcases()

    @property
    def submissions(self) -> Collection[JurySubmission]:
        if self._submissions is None:
            self._submissions = []
            for category_directory in (self.directory / "submissions").iterdir():
                if category_directory.is_dir():
                    for path in category_directory.iterdir():
                        if (
                            path.is_file()
                            and not path.name.endswith(".class")
                            and not path.stem == "impossible"
                        ):
                            self._submissions.append(
                                JurySubmission(path, self.repository)
                            )
        return self._submissions

    @property
    def json_ref(self):
        return self.repository_key

    def __hash__(self):
        return hash(self.repository_key)

    def __eq__(self, other):
        return (
            isinstance(other, RepositoryProblem)
            and self.repository_key == other.repository_key
        )

    def __str__(self):
        return f"P({self.repository_key})"


class RepositoryProblems(ProblemLoader[RepositoryProblem]):
    def __init__(self, repository: "Repository", repository_path=None):
        if repository_path is None:
            repository_path = repository.base_directory / "problems"
        self.base_path = repository_path.resolve()
        self._problems = {}
        self._all_loaded = False
        self.repository = repository

    def load_problem(self, name: str) -> RepositoryProblem:
        if name in self._problems:
            return self._problems[name]
        path = self.base_path / name
        if not path.is_dir() or not (path / "problem.yaml").exists():
            raise KeyError(f"Problem {name} not found")
        problem = RepositoryProblem(path, self.repository)
        self._problems[path.name] = problem
        return problem

    def serialize_problem(self, problem: RepositoryProblem):
        return problem.repository_key

    def load_all_problems(self):
        if not self._all_loaded:
            for path in self.base_path.iterdir():
                if path.is_dir() and (path / "problem.yaml").exists():
                    if path.name not in self._problems:
                        self._problems[path.name] = RepositoryProblem(
                            path, self.repository
                        )
            self._all_loaded = True
        return list(self._problems.values())

    def __iter__(self):
        return iter(self.load_all_problems())

    def __getitem__(self, item):
        return self.load_problem(item)


def recurse_traversable(
    traversable: Traversable,
    action: Callable[[Traversable, list[str]], None],
):
    def _recurse(
        trv: Traversable,
        components: list[str],
    ):
        for child in trv.iterdir():
            components.append(child.name)
            if child.is_file():
                action(child, list(components))
            else:
                _recurse(child, list(components))
            components.pop()

    _recurse(traversable, [])


@dataclasses.dataclass
class TraversableFile(FileData):
    traversable: Traversable
    path: list[str]

    def __post_init__(self):
        assert self.path and all(component for component in self.path)

    def open(self):
        return self.traversable.open(mode="rb")

    @property
    def relative_path(self) -> list[str]:
        return self.path


def get_components_of_traversable(traversable: Traversable) -> Collection[FileData]:
    files = []

    def action(child: Traversable, path: list[str]):
        files.append(TraversableFile(child, path))

    recurse_traversable(traversable, action)
    return files


class Repository(object):
    @staticmethod
    def _default_checker_files() -> Mapping[str, Collection[FileData]]:
        standard_checkers = res.files("pydomjudge.repository.checker")
        by_key = {
            checker.name: get_components_of_traversable(checker)
            for checker in standard_checkers.iterdir()
        }
        Repository._default_checker_files = lambda: by_key
        return by_key

    @staticmethod
    def _get_files_for_default_language(language_key):
        return get_components_of_traversable(
            res.files(f"pydomjudge.repository.compiler.{language_key}")
        )

    @staticmethod
    def _default_language_settings() -> Mapping[str, Mapping[str, Any]]:
        standard_languages = res.files("pydomjudge.repository").joinpath(
            "languages.yml"
        )
        with standard_languages.open(mode="rt") as f:
            language_configuration = yaml.safe_load(f)
        assert isinstance(language_configuration, dict)
        return language_configuration

    @staticmethod
    def _make_language(
        language_key: str,
        language_data: Mapping[str, Any],
        executable_contents: Collection[FileData],
    ):
        compile_script = Executable(
            key=f"compile_{language_key}",
            description=f"compile {language_data['name']}",
            executable_type=ExecutableType.Compile,
            contents=executable_contents,
        )
        return Language(
            key=language_key,
            name=language_data["name"],
            time_factor=language_data.get("time_factor", 1.0),
            extensions=set(language_data["extensions"]),
            entry_point_required=language_data.get("entry_point_required", False),
            entry_point_description=language_data.get("entry_point_description", None),
            compile_script=compile_script,
        )

    @staticmethod
    def parse_language(
        base_directory: pathlib.Path, language_key: str, language_data: dict[str, Any]
    ) -> Language:
        language_directory = base_directory / language_key
        if not language_directory.is_dir():
            raise ValueError(
                f"No language data found for {language_key} (at {language_directory})"
            )
        return Repository._make_language(
            language_key,
            language_data,
            Executable.get_directory_contents(base_directory),
        )

    @staticmethod
    def is_repository(directory: pathlib.Path):
        return (
            directory.is_dir()
            and (directory / "config.yaml").is_file()
            and (directory / "problems").is_dir()
        )

    def __init__(self, base_path: pathlib.Path):
        if not Repository.is_repository(base_path):
            raise ValueError(
                f"Directory {base_path} does not seem to be a Kattis repository"
            )

        self.base_directory = base_path

        config_path = base_path / "config.yaml"
        with config_path.open(mode="rt") as f:
            configuration = yaml.safe_load(f)

        affiliations_by_key: Dict[str, Affiliation] = {
            key: Affiliation.parse(key, data)
            for key, data in configuration.get("affiliations", {}).items()
        }
        self.affiliations: List[Affiliation] = list(affiliations_by_key.values())
        self.authors: List[RepositoryAuthor] = [
            RepositoryAuthor.parse(author, data, affiliations_by_key)
            for author, data in configuration.get("authors", {}).items()
        ]

        self.repository_runscript_directory = base_path / "runscript"

        repository_languages_directory = base_path / "compiler"

        language_settings: dict[str, Any] | list[str] = configuration.get(
            "languages", []
        )
        language_keys: set[str]
        if isinstance(language_settings, dict):
            language_keys = set(language_settings.keys())
        else:
            language_keys = set(language_settings)

        languages: List[Language] = []
        default_language_settings: Mapping[str, Mapping[str, Any]] = (
            Repository._default_language_settings()
        )

        for language_key in language_keys:
            if (
                isinstance(language_settings, Mapping)
                and language_key in language_settings
            ):
                settings = language_settings[language_key]
            elif language_key in default_language_settings:
                settings = default_language_settings[language_key]
            else:
                raise KeyError(f"Unknown language {language_key}")

            if (repository_languages_directory / language_key).exists():
                language = Repository.parse_language(
                    repository_languages_directory, language_key, settings
                )
            else:
                files = Repository._get_files_for_default_language(language_key)
                language = Repository._make_language(language_key, settings, files)
            languages.append(language)

        self.languages: Collection[Language] = tuple(languages)
        self.languages_by_extension: Dict[str, Language] = dict()
        for lang in self.languages:
            for extension in lang.extensions:
                if extension in self.languages_by_extension:
                    raise ValueError(
                        f"Multiple languages have extension {extension}: "
                        f"{lang} and {self.languages_by_extension[extension]}"
                    )
                self.languages_by_extension[extension] = lang
        if not self.languages:
            log.warning("Repository at %s has no languages", base_path)

        if (self.base_directory / "problemset.cls").exists():
            self.problemset_class = self.base_directory / "problemset.cls"
        else:
            self.problemset_class = None

        self.problems = RepositoryProblems(self, base_path / "problems")

    def _find_checker_include_data(self, language: str) -> Collection[FileData]:
        repository_directory = self.base_directory / "checker" / language
        if repository_directory.is_dir():
            log.debug("Using repository checker files from %s", repository_directory)
            return Executable.get_directory_contents(repository_directory)
        default_directory = res.files(f"pydomjudge.repository.checker.{language}")
        if default_directory.is_dir():
            return get_components_of_traversable(default_directory)
        return []

    def find_author_of(self, submission: JurySubmission) -> Optional[RepositoryAuthor]:
        match = None
        for author in self.authors:
            if any(pattern.match(submission.name) for pattern in author.patterns):
                if match is not None:
                    raise KattisRepositoryError(
                        f"Found multiple matching authors ({author}, {match}) for submission {submission}"
                    )
                else:
                    match = author
        return match

    @staticmethod
    def get_checker_data_of(
        problem: RepositoryProblem,
    ) -> tuple[str, pathlib.Path] | None:
        validation_directory = problem.directory / "output_validators"
        checker_directory: pathlib.Path | None = None
        checker_language: str | None = None

        if validation_directory.exists():
            checker_files = list(validation_directory.iterdir())
            if len(checker_files) > 1:
                raise KattisRepositoryError(f"Found multiple checkers for {problem}")
            if checker_files:
                file: pathlib.Path = checker_files[0]
                if file.is_file():
                    suffix_to_language = {
                        ".py": "python",
                        ".c": "c",
                        ".cpp": "cpp",
                        ".java": "java",
                    }
                    if file.suffix not in suffix_to_language:
                        raise KattisRepositoryError(
                            f"Checker file {file.name} for {problem} not understood"
                        )

                    checker_directory = validation_directory
                    checker_language = suffix_to_language[file.suffix]
                elif file.is_dir():
                    directory_to_language = {
                        "checker": "java",
                        "java": "java",
                        "validate": "cpp",
                        "cpp": "cpp",
                        "checker_py": "python",
                        "python": "python",
                        "py": "python",
                    }
                    if file.name not in directory_to_language:
                        raise KattisRepositoryError(
                            f"Checker directory {file.name} for {problem} not understood"
                        )
                    checker_directory = file
                    checker_language = directory_to_language[file.name]
                else:
                    raise KattisRepositoryError(
                        f"Checker for {problem} contains weird file {file.name}"
                    )

        if checker_directory is None:
            if problem.validation == "custom":
                raise KattisRepositoryError(
                    f"Found no checker for custom validation for {problem}"
                )
            return None

        if problem.validation != "custom":
            raise KattisRepositoryError(
                f"Found checkers for non-custom validation for {problem}"
            )
        return checker_language, checker_directory

    def get_checker_of(self, problem: RepositoryProblem) -> Optional[Executable]:
        checker_data = self.get_checker_data_of(problem)
        if checker_data is None:
            return None
        checker_language, checker_directory = checker_data
        checker_files = list(self._find_checker_include_data(checker_language))
        checker_files.extend(Executable.get_directory_contents(checker_directory))

        if not checker_files:
            raise ValueError("Empty checker")
        return Executable(
            f"cmp_{problem.repository_key}",
            f"checker for {problem.repository_key}",
            executable_type=ExecutableType.Compare,
            contents=checker_files,
        )

    # noinspection PyMethodMayBeStatic
    def get_solution_team_of_language(self, language: Language):
        return Team(
            key=f"sol_lang_{language.key}",
            name=f"sol_lang_{language.key}",
            display_name=f"Sample Solution {language.name}",
            category=SystemCategory.Solution,
            affiliation=None,
            members=[],
        )

    # noinspection PyMethodMayBeStatic
    def get_team_of_author(self, author: Optional[RepositoryAuthor]):
        if author is None:
            return Team(
                key="sol_author_unknown",
                name="sol_author_unknown",
                display_name="Author Unknown",
                category=SystemCategory.Author,
                affiliation=None,
                members=[],
            )

        return Team(
            key=f"sol_author_{author.key}",
            name=f"sol_author_{author.key}",
            display_name=f"Author {author.name}",
            category=SystemCategory.Author,
            affiliation=author.affiliation,
            members=[],
        )

    def find_language_of_submission(
        self, submission: JurySubmission
    ) -> Optional[Language]:
        return self.languages_by_extension.get(submission.extension, None)

    def __str__(self):
        return f"KattisRepository[{self.base_directory}]"


def add_arguments(parser: argparse.ArgumentParser):
    parser.add_argument("--repository", type=pathlib.Path)


def from_args(args: argparse.Namespace) -> Repository:
    candidates: List[pathlib.Path]
    cwd = pathlib.Path.cwd()
    if args.repository is None:
        candidates = [cwd / "repository", cwd] + list(cwd.resolve().absolute().parents)
    else:
        candidates = [
            args.repository / "repository",
            args.repository,
            args.repository.parent,
        ]
    for path in candidates:
        if Repository.is_repository(path):
            return Repository(path)

    raise FileNotFoundError(
        f"No repository at path {args.repository if args.repository is not None else cwd}"
    )