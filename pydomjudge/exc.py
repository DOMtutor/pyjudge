import pathlib
import sys
import logging

log = logging.getLogger(__name__)


# TODO Sub-errors and replace generic raises
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


def run_wrapped(func, *args, **kwargs):
    try:
        return func(*args, **kwargs).run()
    except PyJudgeError as e:
        print(f"{e}", file=sys.stderr)
        if log.isEnabledFor(logging.DEBUG):
            log.debug("Error information", exc_info=e)
        sys.exit(1)
