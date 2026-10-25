import functools
import logging
import pathlib
import sys

log = logging.getLogger(__name__)


class PyJudgeError(Exception):
    pass


class UnlikelyInstructionError(PyJudgeError):
    pass


class ConfigurationError(PyJudgeError):
    pass


class InconsistentDataError(PyJudgeError):
    pass


def display_path(path: pathlib.Path) -> str:
    """A path as shown to the user: relative to the working directory if it is
    at most two levels above, else as given."""
    try:
        relative = path.resolve().relative_to(
            pathlib.Path.cwd().resolve(), walk_up=True
        )
    except ValueError:  # e.g. on another drive
        return str(path)
    if relative.parts[:3].count("..") <= 2:
        return str(relative)
    return str(path)


class InvalidFileFormatError(PyJudgeError):
    """A file that cannot be read as what it should be. One problem is shown in
    one line, several below a header line."""

    def __init__(self, source: pathlib.Path | None, *problems: str, what: str = "file"):
        super().__init__(*problems)
        self.source = source
        self.problems = problems
        self.what = what

    def __str__(self):
        name = display_path(self.source) if self.source is not None else self.what
        if len(self.problems) == 1:
            return f"{name}: {self.problems[0]}"
        lines = [f"{name}: invalid {self.what}"]
        lines += [f"  {problem}" for problem in self.problems]
        return "\n".join(lines)


class ProblemVerificationError(PyJudgeError):
    pass


class ElementNotFoundError(PyJudgeError):
    pass


class MultipleElementsFoundError(PyJudgeError):
    pass


def validation_problems(error) -> list[str]:
    """A pydantic ValidationError as "location: message" lines."""
    problems = []
    for detail in error.errors(include_url=False):
        location = ""
        for part in detail["loc"]:
            location += f"[{part}]" if isinstance(part, int) else f".{part}"
        location = location.lstrip(".")
        problems.append(f"{location}: {detail['msg']}" if location else detail["msg"])
    return problems


def describe_error(error: BaseException) -> str:
    """The message shown for an error that ends a command."""
    import pydantic
    import yaml

    if isinstance(error, PyJudgeError):
        return str(error)
    if isinstance(error, pydantic.ValidationError):
        return "\n".join(validation_problems(error))
    if isinstance(error, yaml.YAMLError):
        return f"Invalid YAML: {error}"
    if type(error).__module__.startswith("pymysql"):
        detail = error.args[1] if len(error.args) > 1 else error
        return (
            f"Database error: {detail}\n"
            "Check the database configuration (db.yml or --db) and that DOMjudge's "
            "database is running."
        )
    if isinstance(error, OSError) and error.filename:
        return f"{error.filename}: {error.strerror}"
    return f"Unexpected error: {error!r}"


def error_handler_wrapper(func):
    """Run a command; report errors in a few lines, the traceback with --debug."""

    @functools.wraps(func)
    def run_wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except KeyboardInterrupt:
            sys.exit(130)
        except Exception as e:
            message = describe_error(e)
            print(message, file=sys.stderr)
            if log.isEnabledFor(logging.DEBUG):
                log.debug("Traceback", exc_info=e)
            elif message.startswith("Unexpected error"):
                print("(run with --debug for the traceback)", file=sys.stderr)
            sys.exit(1)

    return run_wrapped
