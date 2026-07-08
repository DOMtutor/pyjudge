import enum
from typing import Annotated

from pydantic import PlainSerializer, BeforeValidator


class SubmissionVerdict(enum.Enum):
    COMPILER_ERROR = "COMPILER_ERROR", "compiler-error"
    PRESENTATION_ERROR = "PRESENTATION_ERROR", "presentation-error"
    CORRECT = "CORRECT", "correct"
    TIME_LIMIT = "TIMELIMIT", "time-limit"
    MEMORY_LIMIT = "MEMORY_LIMIT", "memory-limit"
    OUTPUT_LIMIT = "OUTPUT_LIMIT", "output-limit"
    RUN_ERROR = "RUN_ERROR", "run-error"
    WRONG_ANSWER = "WRONG-ANSWER", "wrong-answer"
    NO_OUTPUT = "NO_OUTPUT", "no-output"

    @staticmethod
    def parse_from_expected_result(key):
        for verdict in SubmissionVerdict:
            if verdict.expected_result_key() == key:
                return verdict
        raise KeyError(key)

    @staticmethod
    def from_string(key):
        for verdict in SubmissionVerdict:
            if str(verdict) == key:
                return verdict
        raise KeyError(key)

    def expected_result_key(self):
        return self.value[0]

    def __str__(self):
        return self.value[1]


PydanticVerdict = Annotated[
    SubmissionVerdict,
    PlainSerializer(str, when_used="json"),
    BeforeValidator(
        lambda v: SubmissionVerdict.from_string(v) if isinstance(v, str) else v
    ),
]


class TestcaseVerdict(enum.StrEnum):
    PRESENTATION_ERROR = "presentation_error"
    CORRECT = "correct"
    TIME_LIMIT = "timelimit"
    MEMORY_LIMIT = "memory-limit"
    OUTPUT_LIMIT = "output-limit"
    RUN_ERROR = "run-error"
    WRONG_ANSWER = "wrong-answer"
    NO_OUTPUT = "no-output"

    @staticmethod
    def from_string(key):
        for verdict in TestcaseVerdict:
            if verdict.value == key:
                return verdict
        raise KeyError(key)

    def __str__(self):
        return self.value


PydanticTestcaseVerdict = Annotated[
    TestcaseVerdict,
    PlainSerializer(str, when_used="json"),
    BeforeValidator(
        lambda v: TestcaseVerdict.from_string(v) if isinstance(v, str) else v
    ),
]
