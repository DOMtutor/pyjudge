import abc
import dataclasses
import enum
from typing import Optional, Set

from .language import Language
from .util import get_md5


class Verdict(enum.Enum):
    COMPILER_ERROR = "COMPILER_ERROR"
    PRESENTATION_ERROR = "PRESENTATION_ERROR"
    CORRECT = "CORRECT"
    TIME_LIMIT = "TIMELIMIT"
    MEMORY_LIMIT = "MEMORY_LIMIT"
    OUTPUT_LIMIT = "OUTPUT_LIMIT"
    RUN_ERROR = "RUN_ERROR"
    WRONG_ANSWER = "WRONG-ANSWER"
    NO_OUTPUT = "NO_OUTPUT"

    @staticmethod
    def parse_from_judge(key):
        for verdict in Verdict:
            if verdict.value == key:
                return verdict
        raise KeyError(key)

    @staticmethod
    def get(key):
        for verdict in Verdict:
            if verdict.name == key:
                return verdict
        raise KeyError(key)


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
    def source(self):
        pass

    def source_md5(self) -> str:
        return get_md5(self.source)


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
