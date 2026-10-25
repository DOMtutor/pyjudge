import enum
from typing import Annotated, Any

from pydantic import BeforeValidator


class Verdict(enum.StrEnum):
    """Result of a judging or of a single test case run.

    The values are DOMjudge's result strings (``judging.result``,
    ``judging_run.runresult`` and the ``results_prio`` configuration). Being a
    ``StrEnum``, a verdict serialises to its value, also as a JSON object key.
    """

    CORRECT = "correct"
    COMPILER_ERROR = "compiler-error"
    TIME_LIMIT = "timelimit"
    RUN_ERROR = "run-error"
    MEMORY_LIMIT = "memory-limit"
    OUTPUT_LIMIT = "output-limit"
    NO_OUTPUT = "no-output"
    WRONG_ANSWER = "wrong-answer"

    def expected_result_key(self) -> str:
        """The spelling DOMjudge uses in ``submission.expected_results``."""
        return self.value.upper()

    @classmethod
    def parse(cls, text: str) -> "Verdict":
        """Parse a DOMjudge result string, case-insensitively (DOMjudge
        upper-cases them in ``submission.expected_results``)."""
        normalized = text.strip().lower()
        try:
            return cls(normalized)
        except ValueError:
            raise ValueError(f"Unknown verdict {text!r}") from None


def _parse_if_string(value: Any) -> Any:
    return Verdict.parse(value) if isinstance(value, str) else value


PydanticVerdict = Annotated[Verdict, BeforeValidator(_parse_if_string)]
