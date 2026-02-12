import sys
import logging

log = logging.getLogger(__name__)


# TODO Sub-errors and replace generic raises
class PyJudgeError(Exception):
    pass


def run_wrapped(func, *args, **kwargs):
    try:
        return func(*args, **kwargs).run()
    except PyJudgeError as e:
        print(f"{e}", file=sys.stderr)
        if log.isEnabledFor(logging.DEBUG):
            log.debug("Error information", exc_info=e)
        sys.exit(1)
