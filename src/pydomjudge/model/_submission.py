import abc

from pydantic import BaseModel

from ._language import Language
from ._util import get_md5
from ._verdict import SubmissionVerdict


class ProblemSubmission(abc.ABC):
    # TODO support multiple files?

    @property
    @abc.abstractmethod
    def name(self) -> str:
        pass

    @abc.abstractmethod
    def last_modified(self) -> float:
        pass

    @property
    @abc.abstractmethod
    def file_name(self) -> str:
        pass

    @property
    @abc.abstractmethod
    def language(self) -> Language | None:
        pass

    @property
    @abc.abstractmethod
    def expected_results(self) -> set[SubmissionVerdict] | None:
        pass

    @property
    @abc.abstractmethod
    def source(self) -> str:
        pass

    def source_md5(self) -> str:
        return get_md5(self.source.encode("utf-8"))

    def __str__(self):
        # noinspection PyTypeChecker
        return f"S({self.name}@{','.join(str(x) for x in self.expected_results) if self.expected_results else '?'})"


class SubmissionAuthor(BaseModel):
    key: str
    name: str

    def __str__(self):
        return f"{self.name}"


class JuryProblemSubmission(ProblemSubmission):
    @property
    @abc.abstractmethod
    def author(self) -> SubmissionAuthor | None:
        pass
