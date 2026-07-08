import functools
import pathlib
import sys
import logging

log = logging.getLogger(__name__)


class PyJudgeError(Exception):
    pass


class UnlikelyInstructionError(PyJudgeError):
    pass


class ConfigurationError(PyJudgeError):
    pass


class InconsistentDataError(PyJudgeError):
    pass


class InvalidFileFormatError(PyJudgeError):
    def __init__(self, source: pathlib.Path | None, *args):
        super().__init__(*args)
        self.source = source


class ElementNotFoundError(PyJudgeError):
    pass


class MultipleElementsFoundError(PyJudgeError):
    pass


def error_handler_wrapper(func):
    @functools.wraps(func)
    def run_wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except PyJudgeError as e:
            print(f"{e}", file=sys.stderr)
            log.debug("Error information", exc_info=e)
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected error: {e}", file=sys.stderr)
            log.error("Stacktrace", exc_info=e)
            sys.exit(1)

    return run_wrapped
