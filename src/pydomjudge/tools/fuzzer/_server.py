"""Web interface of the fuzzer.

Run it with ``dt_fuzzer --repository PATH`` (Flask development server) or with
gunicorn as ``pydomjudge.tools.fuzzer:create_app()``, configured through the
environment variables PYJUDGE_REPOSITORY and PYJUDGE_BASE_TIME. Fuzzing runs
live in the memory of the process, so use a single worker.
"""

import argparse
import logging
import os
import pathlib
import threading
import uuid
from dataclasses import dataclass, field
from io import StringIO
from typing import Annotated

from flask import Blueprint, Flask, current_app, jsonify, redirect, request, url_for
from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    model_validator,
)

from pydomjudge.exc import ConfigurationError
from pydomjudge.model import JudgeInstance
from pydomjudge.repository.kattis import Repository, RepositoryProblem

from ._fuzzer import Fuzzer, FuzzingRequest

log = logging.getLogger(__name__)

EXTENSION_KEY = "pydomjudge"

# problemtools calls some languages differently than the repository
PROBLEMTOOLS_LANGUAGE = {"python": "python3"}

# DOMjudge's SubmissionService::FILENAME_REGEX; in particular no path separators
FileName = Annotated[
    str, StringConstraints(pattern=r"^[a-zA-Z0-9_][a-zA-Z0-9+_.-]*$", max_length=255)
]


class FuzzingRequestBody(BaseModel):
    """JSON body of POST /submission.

    Validation needs the repository data, passed as validation context
    {"state": FuzzerState}.
    """

    problem: str
    language: str | None = Field(
        default=None, description="Repository language key, None to detect"
    )
    sources: dict[FileName, Annotated[str, Field(max_length=1_000_000)]] = Field(
        min_length=1, max_length=20
    )
    case_name: str = Field(description="Name of a seed file of the problem")
    runs: int = Field(default=10, ge=1, le=1000)

    @model_validator(mode="after")
    def _check_against_repository(self, info: ValidationInfo):
        state: FuzzerState | None = (info.context or {}).get("state")
        if state is None:
            raise ValueError("No fuzzer state given for validation")
        problem = state.problems.get(self.problem)
        if problem is None:
            raise ValueError(f"Unknown problem {self.problem}")
        if self.language is not None and self.language not in state.language_keys:
            known = ", ".join(sorted(state.language_keys))
            raise ValueError(f"Unknown language {self.language} (known: {known})")
        if self.case_name not in seed_names(problem):
            raise ValueError(f"Problem {self.problem} has no seed {self.case_name}")
        return self


def seed_names(problem: RepositoryProblem) -> list[str]:
    secret = problem.directory / "data" / "secret"
    return sorted(seed.stem for seed in secret.glob("*.seed"))


class FuzzingThread(threading.Thread):
    FORMATTER = logging.Formatter("%(message)s")

    def __init__(self, fuzzer_id: str, fuzzer: Fuzzer, fuzzing_request: FuzzingRequest):
        super().__init__(daemon=True)
        self.fuzzer_id = fuzzer_id
        self.fuzzer = fuzzer
        self.request = fuzzing_request
        self.state: dict = {"id": self.fuzzer_id, "finished": False}
        self.log_stream = StringIO()

    def run(self):
        submission_logger = self.request.logger
        handler = logging.StreamHandler(self.log_stream)
        handler.setFormatter(self.FORMATTER)
        for existing in list(submission_logger.handlers):
            submission_logger.removeHandler(existing)
        submission_logger.addHandler(handler)
        submission_logger.setLevel(logging.DEBUG)
        submission_logger.propagate = False  # shown to the user, not in the app log

        try:
            result = self.fuzzer.run(self.request)
            if result is not None:
                self.state["cases"] = {
                    f"{index + 1}_{run_result.verdict}": {
                        "case.in": run_result.input,
                        "case.ans": run_result.answer,
                    }
                    for index, run_result in enumerate(result.run_results)
                }
            log.info("Finished fuzzing run %s", self.fuzzer_id)
        except Exception as e:
            log.warning("Unexpected error", exc_info=e)
            submission_logger.error("Unexpected error: %s", e)
        finally:
            handler.flush()
            # Keep the log, also of failed runs, before closing the stream
            self.state["log"] = self.log_stream.getvalue()
            submission_logger.removeHandler(handler)
            self.log_stream.close()
            self.state["finished"] = True

    def get_state(self) -> dict:
        current = self.state.copy()
        if not current["finished"]:
            current["log"] = self.log_stream.getvalue()
        return current


@dataclass
class FuzzerState:
    """Everything the request handlers need, stored in app.extensions."""

    repository: Repository
    problems: dict[str, RepositoryProblem]
    base_time: float
    fuzzer: Fuzzer = field(default_factory=Fuzzer)
    runs: dict[str, FuzzingThread] = field(default_factory=dict)

    @property
    def language_keys(self) -> set[str]:
        return {language.key for language in self.repository.languages}

    def start(self, body: FuzzingRequestBody) -> str:
        problem = self.problems[body.problem]
        fuzzing_id = str(uuid.uuid4())
        language = body.language
        fuzzing_request = FuzzingRequest(
            sources=body.sources,
            language=PROBLEMTOOLS_LANGUAGE.get(language, language)
            if language
            else None,
            problem=problem,
            seed_file=problem.directory / "data" / "secret" / f"{body.case_name}.seed",
            logger=logging.getLogger(f"{__name__}.run.{fuzzing_id}"),
            time_limit=round(self.base_time * problem.limits.time_factor, 1),
            run_count=body.runs,
        )
        thread = FuzzingThread(fuzzing_id, self.fuzzer, fuzzing_request)
        self.runs[fuzzing_id] = thread
        thread.start()
        return fuzzing_id


def state() -> FuzzerState:
    return current_app.extensions[EXTENSION_KEY]


main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def home():
    return redirect(url_for("static", filename="client.html"))


@main_bp.route("/problems")
def show_problems():
    return jsonify(success=True, problems=sorted(state().problems))


@main_bp.route("/problem/<problem_name>/seeds", methods=["GET"])
def get_problem_seeds(problem_name):
    problem = state().problems.get(problem_name)
    if problem is None:
        return jsonify(success=False, errors=["No such problem"])
    return jsonify(success=True, seeds=seed_names(problem))


@main_bp.route("/status")
def show_status():
    status = {key: run.get_state() for key, run in state().runs.items()}
    return jsonify(success=True, status=status)


@main_bp.route("/submission", methods=["POST"])
def start_fuzzing():
    try:
        body = FuzzingRequestBody.model_validate(
            request.get_json(silent=True), context={"state": state()}
        )
    except ValidationError as e:
        errors = [
            f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()
        ]
        log.debug("Invalid request: %s", errors)
        return jsonify(success=False, errors=errors)
    return jsonify(success=True, id=state().start(body))


@main_bp.route("/submission/<fuzzing_id>", methods=["GET"])
def show_single_status(fuzzing_id):
    run = state().runs.get(fuzzing_id)
    if run is None:
        return jsonify(success=False, errors=["Id not found"])
    return jsonify(success=True, state=run.get_state())


@main_bp.route("/submission/<fuzzing_id>", methods=["DELETE"])
def stop_fuzzing(fuzzing_id):
    # Forgets the run; a running thread finishes in the background
    run = state().runs.pop(fuzzing_id, None)
    if run is None:
        return jsonify(success=False, state=None)
    return jsonify(success=True, state=run.get_state())


def create_app(
    repository_path: pathlib.Path | str | None = None,
    base_time: float | None = None,
) -> Flask:
    """The fuzzer app. Arguments not given are taken from the environment
    variables PYJUDGE_REPOSITORY and PYJUDGE_BASE_TIME (default 1.0)."""
    if repository_path is None:
        repository_path = os.environ.get("PYJUDGE_REPOSITORY")
        if not repository_path:
            raise ConfigurationError(
                "No repository given; pass --repository or set PYJUDGE_REPOSITORY"
            )
    if base_time is None:
        base_time = float(os.environ.get("PYJUDGE_BASE_TIME", "1.0"))
    repository_path = pathlib.Path(repository_path)
    if not Repository.is_repository(repository_path):
        raise ConfigurationError(f"{repository_path} is not a problem repository")

    repository = Repository(repository_path)
    problems = {
        problem.repository_key: problem
        for problem in repository.problems
        if seed_names(problem)
    }
    if not problems:
        raise ConfigurationError("Found no problems with seed files")
    log.info("Found %d problems with seeds", len(problems))

    app = Flask(__name__)
    app.extensions[EXTENSION_KEY] = FuzzerState(
        repository=repository, problems=problems, base_time=base_time
    )
    app.register_blueprint(main_bp)
    return app


def run_app():
    parser = argparse.ArgumentParser(description="Fuzzer for seeded test data")
    parser.add_argument(
        "-r", "--repository", type=pathlib.Path, required=True, help="Repository"
    )
    time_group = parser.add_mutually_exclusive_group()
    time_group.add_argument(
        "--base-time",
        type=float,
        help="Base time limit in seconds, multiplied by the problem's factor "
        "(default 1.0)",
    )
    time_group.add_argument(
        "--instance", type=pathlib.Path, help="Take the base time from instance.json"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true", help="Flask debug mode")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s %(message)s",
    )
    logging.getLogger("pydomjudge").setLevel(logging.DEBUG if args.debug else "INFO")

    base_time = args.base_time
    if args.instance is not None:
        base_time = JudgeInstance.model_validate_json(
            args.instance.read_text()
        ).base_time
    create_app(args.repository, base_time).run(
        host=args.host, port=args.port, debug=args.debug
    )
