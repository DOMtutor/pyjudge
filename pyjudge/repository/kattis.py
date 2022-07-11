import dataclasses
import logging
import mimetypes
import pathlib
import re
import subprocess
from typing import Optional, List, Dict, Tuple, Collection, Set

import yaml

from pyjudge.model import *
from pyjudge.model.util import get_md5

base_directory = pathlib.Path(__file__).parent.parent


class MakeError(Exception):
    def __init__(self, rules, code, out, err):
        self.rules = rules
        self.code = code
        self.out = out
        self.err = err


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
                    logging.warning("Found multiple images for submission %s", self)
                else:
                    extension = mimetypes.guess_extension(mimetype)
                    if extension is None:
                        logging.warning("Could not find extension for mimetype %s", mimetype)
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
    affiliation: Affiliation

    @staticmethod
    def parse(key, data):
        if "regex" in data:
            regexes = data["regex"]
            if isinstance(regexes, str):
                regexes = [regexes]
            patterns = [re.compile(regex) for regex in regexes]
        else:
            regexes = data["basic_regex"]
            if isinstance(regexes, str):
                regexes = [regexes]
            patterns = [re.compile(rf"^[a-zA-z\d_-]*{regex}[a-zA-z\d_-]*$") for regex in regexes]
        return RepositoryAuthor(key=key, name=data["name"], patterns=patterns,
                                affiliation=Affiliation(short_name="tum", name="TUM", country="DEU"))


class JurySubmission(JuryProblemSubmission):
    EXPECTED_RESULTS = {
        'accepted': [Verdict.CORRECT],
        'too_slow': [Verdict.TIME_LIMIT],
        'time_limit_exceeded': [Verdict.TIME_LIMIT],
        'timelimit_exceeded': [Verdict.TIME_LIMIT],
        'slow_input': [Verdict.CORRECT, Verdict.TIME_LIMIT],
        'slow': [Verdict.CORRECT, Verdict.TIME_LIMIT],
        'run_time_error': [Verdict.RUN_ERROR],
        'runtime_error': [Verdict.RUN_ERROR],
        'wrong_answer': [Verdict.WRONG_ANSWER],
        'compile_error': [Verdict.COMPILER_ERROR]
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
            source_code: str = source_bytes.decode(encoding='utf-8', errors='strict')
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
    DIFFICULTIES = ["very easy", "easy", "medium", "hard", "very hard", "unknown"]
    UNKNOWN_DIFFICULTY = "unknown"

    def __init__(self, directory: pathlib.Path, config: "Repository"):
        self.config = config
        self.repository_key = directory.name
        self.directory = directory
        description_file = self.directory / "problem.yaml"
        if not description_file.is_file():
            raise ValueError(f"Problem {self.repository_key} not found at {description_file}")
        with description_file.open(mode="rt", encoding="utf-8") as f:
            self.description = yaml.safe_load(f)

        self._name = self.description["name"]
        if self.description and "keywords" in self.description:
            keywords = re.split(" - |,", self.description["keywords"])
            self.keywords = list([x.strip().lower() for x in keywords])  # replace("-", " ")?
        else:
            self.keywords = []

        difficulty = None
        for keyword in self.keywords:
            if keyword in RepositoryProblem.DIFFICULTIES:
                if difficulty is not None:
                    raise ValueError(f"Found difficulties {difficulty} and {keyword} for problem {self.repository_key}")
                difficulty = keyword
        if difficulty is None:
            difficulty = RepositoryProblem.UNKNOWN_DIFFICULTY
        self.difficulty = difficulty

        self._validator_flags = self.description.get("validator_flags", None)
        self.validation = self.description.get("validation")

        limits = self.description.get("limits", {})
        time_s = limits.get("time_limit", 1.0)
        if "time_multiplier" in limits:
            time_s *= limits["time_multiplier"]
        self._limits = ProblemLimits(
            time_s=time_s,
            memory_kib=limits.get("memory_limit", None),
            output_kib=limits.get("output_limit", None),
        )

        self._test_cases = None
        self._solutions = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def limits(self) -> ProblemLimits:
        return self._limits

    def check(self):
        self.make("validate-input", timeout=600)

    @property
    def checker_flags(self) -> Optional[str]:
        return self._validator_flags

    @property
    def key(self) -> str:
        return self.repository_key

    @property
    def checker(self) -> Optional[Executable]:
        return self.config.get_checker_of(self)

    @property
    def problem_text(self) -> Tuple[bytes, str]:
        problem_pdf = self.directory / "build" / "problem.en.pdf"
        if not problem_pdf.exists():
            self.make("problem")
            if not problem_pdf.exists():
                raise ValueError(f"Missing problem pdf")
        with problem_pdf.open(mode="rb") as f:
            return f.read(), "pdf"

    @property
    def testcases(self):
        self.make("output", timeout=60)

        if self._test_cases is None:
            self._test_cases = []
            for category_directory in (self.directory / "data").iterdir():
                if category_directory.is_dir():
                    for input_file in category_directory.glob("*.in"):
                        if not input_file.is_file():
                            continue
                        case_name = input_file.name[:-3]
                        answer_file = category_directory / (case_name + ".ans")
                        if not answer_file.is_file():
                            continue
                        self._test_cases.append(RepositoryTestCase(category_directory / case_name))
        return self._test_cases

    @property
    def submissions(self) -> Collection[JurySubmission]:
        if self._solutions is None:
            self._solutions = []
            for category_directory in (self.directory / "submissions").iterdir():
                if category_directory.is_dir():
                    for path in category_directory.iterdir():
                        if path.is_file() and not path.name.endswith(".class") and not path.stem == "impossible":
                            self._solutions.append(JurySubmission(path, self.config))
        return self._solutions

    def make(self, *args, timeout=10):
        rules = list(map(str, args))
        logging.debug("%s: make %s", self, " ".join(rules))
        call = ["make"] + rules

        process = subprocess.Popen(call, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   encoding="utf-8", cwd=str(self.directory))
        try:
            out, err = process.communicate(timeout=timeout)
            return_code = process.poll()
            if return_code is None:
                logging.debug("Timeout, killing make process")
                process.terminate()
                kill_out, kill_err = process.communicate(timeout=10)
                out += kill_out
                err += kill_err
                return_code = process.poll()
                if return_code is None:
                    logging.warning("Failed to kill process after timeout")
                    process.kill()
            if return_code != 0:
                raise MakeError(rules, return_code, out, err)
        finally:
            if process.returncode is None:
                process.kill()

    @property
    def json_ref(self):
        return self.repository_key

    def __hash__(self):
        return hash(self.repository_key)

    def __eq__(self, other):
        return isinstance(other, RepositoryProblem) and self.repository_key == other.repository_key

    def __str__(self):
        return f"P({self.repository_key})"


class RepositoryProblems(ProblemLoader[RepositoryProblem]):
    def __init__(self, repository: "Repository", repository_path=(base_directory / "problems")):
        self.base_path = repository_path.resolve()
        self._problems = {}
        self._all_loaded = False
        self.repository = repository

    def load_problem(self, name: str) -> RepositoryProblem:
        if name in self._problems:
            return self._problems[name]
        path = self.base_path / name
        if not path.is_dir() or not (path / "problem.yaml").exists():
            raise KeyError
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
                        self._problems[path.name] = RepositoryProblem(path, self.repository)
            self._all_loaded = True
        return list(self._problems.values())

    def __iter__(self):
        return iter(self.load_all_problems())


class Repository(object):
    @staticmethod
    def parse_verdict(key):
        return {
            "correct": Verdict.CORRECT,
            "wrong_answer": Verdict.WRONG_ANSWER,
            "time_limit": Verdict.TIME_LIMIT,
            "run_error": Verdict.RUN_ERROR,
            "memory_limit": Verdict.MEMORY_LIMIT,
            "output_limit": Verdict.OUTPUT_LIMIT,
            "no_output": Verdict.NO_OUTPUT
        }[key]

    @staticmethod
    def parse_scoring(data) -> ScoringSettings:
        priorities: Dict[Verdict, int] = dict()
        for key, priority in data["results_priority"].items():
            priorities[Repository.parse_verdict(key)] = priority

        return ScoringSettings(penalty_time=data["penalty_time"], result_priority=priorities)

    def parse_language(self, key: str, data) -> Language:
        language_directory = self.language_base_directory / key
        if not language_directory.is_dir():
            raise ValueError(f"No language data found for {key} (at {language_directory})")

        compile_script = Executable(key=f"compile_{key}", description=f"compile {data['name']}",
                                    executable_type=ExecutableType.Compile,
                                    contents=Executable.get_directory_contents(language_directory))
        return Language(
            key=key,
            name=data["name"],
            time_factor=data.get("time_factor", 1.0),
            extensions=set(data["extensions"]),
            entry_point_required=data.get("entry_point_required", False),
            entry_point_description=data.get("entry_point_description", None),
            compile_script=compile_script
        )

    def __init__(self, base_path=base_directory):
        with (base_path / "config.yaml").open(mode="rt") as f:
            configuration = yaml.safe_load(f)
        self.base_directory = base_path
        self.checkers_base_directory = base_path / "checkers"
        self.language_base_directory = base_path / "languages"
        self.runscript_directory = base_path / "runscript"

        self.authors: List[RepositoryAuthor] = [RepositoryAuthor.parse(author, data)
                                                for author, data in configuration.get("authors", {}).items()]
        self.languages: List[Language] = [self.parse_language(lang, data)
                                          for lang, data in configuration.get("languages", {}).items()]
        self.judge_user_whitelist: Set[str] = set(configuration.get("user_whitelist", []))

        self.languages_by_extension: Dict[str, Language] = dict()
        for lang in self.languages:
            for extension in lang.extensions:
                if extension in self.languages_by_extension:
                    raise ValueError(f"Multiple languages have extension {extension}: "
                                     f"{lang} and {self.languages_by_extension[extension]}")
                self.languages_by_extension[extension] = lang

        scoring = Repository.parse_scoring(configuration["score"])
        judging = JudgingSettings(**configuration["judging"])
        display = DisplaySettings(**configuration["display"])
        clarification = ClarificationSettings(**configuration["clarification"])
        self.judge_settings: JudgeSettings = JudgeSettings(judging=judging, scoring=scoring,
                                                           display=display, clarification=clarification)
        self.problems = RepositoryProblems(self, base_path / "problems")

    def find_author_of(self, submission: JurySubmission) -> Optional[RepositoryAuthor]:
        match = None
        for author in self.authors:
            if any(pattern.match(submission.name) for pattern in author.patterns):
                if match is not None:
                    raise ValueError(f"Found multiple matching authors ({author}, {match}) for submission {submission}")
                else:
                    match = author
        return match

    def get_checker_of(self, problem: RepositoryProblem) -> Optional[Executable]:
        problem_checkers = {
            "java": [(problem.directory / "output_validators" / "checker")],
            "cpp": [(problem.directory / "output_validators" / "validate")],
            "python": [(problem.directory / "output_validators" / "checker_py")],
        }

        checker_directory = None
        checker_base = None
        for key, directories in problem_checkers.items():
            for directory in directories:
                if directory.is_dir():
                    if checker_directory is not None:
                        raise ValueError("Found multiple checkers")
                    checker_directory = directory
                    checker_base = self.checkers_base_directory / key

        if checker_directory is None:
            if problem.validation == "custom":
                raise ValueError(f"Found no checker for custom validation")
            return None

        if problem.validation != "custom":
            raise ValueError("Found checkers for non-custom validation")

        files = {}
        files.update(Executable.get_directory_contents(checker_base))
        files.update(Executable.get_directory_contents(checker_directory))

        if not files:
            raise ValueError("Empty checker")
        return Executable(f"cmp_{problem.repository_key}", f"checker for {problem.repository_key}",
                          executable_type=ExecutableType.Compare, contents=files)

    def get_solution_team_of_language(self, language: Language):
        return Team(name=f"sol_lang_{language.key}", display_name=f"Sample Solution {language.name}",
                    category=TeamCategory.Solution, affiliation=None, members=[])

    def get_team_of_author(self, author: Optional[RepositoryAuthor]):
        if author is None:
            return Team(name="sol_author_unknown", display_name="Author Unknown",
                        category=TeamCategory.Solution, affiliation=None, members=[])
        return Team(name=f"sol_author_{author.key}", display_name=f"Author {author.name}",
                    category=TeamCategory.Solution, affiliation=author.affiliation, members=[])

    def get_default_runscript(self) -> Dict[str, pathlib.Path]:
        if not self.runscript_directory.is_dir():
            raise ValueError(f"No runscript found at {self.runscript_directory}")

        return {path.relative_to(self.runscript_directory): path for
                path in self.runscript_directory.rglob("*") if path.is_file()}

    def find_language_of_submission(self, submission: JurySubmission) -> Optional[Language]:
        return self.languages_by_extension.get(submission.extension, None)