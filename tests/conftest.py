import os
import pathlib

import pytest

from pydomjudge.database import (
    ClarificationDto,
    ContestDataExport,
    ContestDescriptionDto,
    SubmissionDto,
    SubmissionFileDto,
    TeamDto,
    TestcaseResultDto as CaseResultDto,  # Test* would be collected by pytest
    UserDto,
)
from pydomjudge.model import Verdict

ROOT = pathlib.Path(__file__).resolve().parent.parent


def pytest_configure(config):
    # problemtools forks: keep numpy (imported through copydetect) from starting
    # a BLAS thread pool and tqdm from starting its monitor thread before
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    import tqdm

    tqdm.tqdm.monitor_interval = 0


@pytest.fixture(autouse=True)
def _no_user_configuration(tmp_path_factory, monkeypatch):
    """Keep ~/.config/pyjudge/config.yaml out of the tests."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("config")))


@pytest.fixture(scope="session")
def examples_dir() -> pathlib.Path:
    return ROOT / "examples"


@pytest.fixture
def contest_export() -> ContestDataExport:
    """A small export with every kind of entry."""
    return _export()


def _export() -> ContestDataExport:
    submission = SubmissionDto(
        team_name="t",
        contest_key="c",
        contest_problem_key="A",
        problem_name="p",
        language_key="python",
        submission_time=1.0,
        verdict=Verdict.TIME_LIMIT,
        case_result=[
            CaseResultDto(
                runtime=0.5, verdict=Verdict.TIME_LIMIT, is_sample=False, test_name="x"
            )
        ],
        too_late=False,
        files=[SubmissionFileDto(filename="a.py", content=b"print(1)\n")],
    )
    pending = submission.model_copy(update={"verdict": None, "case_result": []})
    return ContestDataExport(
        description=ContestDescriptionDto(contest_key="c", start=0.0, end=10.0),
        users={
            "u": UserDto(
                login_name="u", display_name="U", external_id="e", email="u@x"
            ),
            "v": UserDto(login_name="v", display_name="V"),
        },
        teams={
            "t": TeamDto(
                name="t",
                display_name="Team T",
                category_name="participants",
                affiliation_name=None,
                member_login_names=["u", "v"],
            )
        },
        languages={"python": "Python 3"},
        problems={"A": "p"},
        submissions=[submission, pending],
        clarifications=[
            ClarificationDto(
                team_name="t",
                contest_key="c",
                contest_problem_key=None,
                request_time=2.0,
                identifier="1",
                response_to=None,
                from_jury=False,
                body="?",
            )
        ],
    )
