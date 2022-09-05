import abc
import dataclasses
import enum
from typing import Optional, Set

from .language import Language
from .util import get_md5


class Verdict(enum.Enum):
    COMPILER_ERROR = "COMPILER_ERROR", "compiler_error"
    PRESENTATION_ERROR = "PRESENTATION_ERROR", "presentation_error"
    CORRECT = "CORRECT", "correct"
    TIME_LIMIT = "TIMELIMIT", "time_limit"
    MEMORY_LIMIT = "MEMORY_LIMIT", "memory_limit"
    OUTPUT_LIMIT = "OUTPUT_LIMIT", "output_limit"
    RUN_ERROR = "RUN_ERROR", "run_error"
    WRONG_ANSWER = "WRONG-ANSWER", "wrong_answer"
    NO_OUTPUT = "NO_OUTPUT", "no_output"

    @staticmethod
    def parse_from_judge(key):
        for verdict in Verdict:
            if verdict.value[0] == key:
                return verdict
        raise KeyError(key)

    @staticmethod
    def parse(key):
        for verdict in Verdict:
            if verdict.value[1] == key:
                return verdict
        raise KeyError(key)

    def serialize(self):
        return self.value[1]

    def __str__(self):
        return self.serialize()


class ProblemSubmission(abc.ABC):
    # TODO support multiple files?

    @property
    @abc.abstractmethod
    def name(self) -> str:
        pass

    @property
    @abc.abstractmethod
    def file_name(self) -> str:
        pass

    @property
    @abc.abstractmethod
    def language(self) -> Optional[Language]:
        pass

    @property
    @abc.abstractmethod
    def expected_results(self) -> Optional[Set[Verdict]]:
        pass

    @property
    @abc.abstractmethod
    def source(self) -> str:
        pass

    def source_md5(self) -> str:
        return get_md5(self.source.encode("utf-8"))


@dataclasses.dataclass
class SubmissionAuthor(object):
    key: str
    name: str

    def __hash__(self):
        return hash(self.key)

    def __eq__(self, other):
        return isinstance(other, SubmissionAuthor) and self.key == other.key

    def __str__(self):
        return f"{self.name}"


class JuryProblemSubmission(ProblemSubmission):
    @property
    @abc.abstractmethod
    def author(self) -> Optional[SubmissionAuthor]:
        pass

    @property
    @abc.abstractmethod
    def problem_unique_name(self) -> str:
        pass

    def __str__(self):
        return f"S({self.problem_unique_name}@{','.join(map(str, self.expected_results))})"
