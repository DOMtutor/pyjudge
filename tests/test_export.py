"""Contest exports (database DTOs): JSON format and round trip."""

import json

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


def test_export_roundtrip():
    export = _export()
    assert ContestDataExport.model_validate_json(export.model_dump_json()) == export
    assert ContestDataExport.model_validate(export.model_dump()) == export


def test_export_json_format():
    data = json.loads(_export().model_dump_json())
    # users and teams are maps keyed by login / team name, with short field names
    assert data["users"]["u"] == {"name": "U", "external_id": "e", "email": "u@x"}
    assert data["users"]["v"] == {"name": "V"}
    assert data["teams"]["t"] == {
        "name": "Team T",
        "category": "participants",
        "affiliation": None,
        "members": ["u", "v"],
    }
    submission = data["submissions"][0]
    assert submission["team_name"] == "t"
    assert submission["verdict"] == "timelimit"
    assert submission["case_result"][0]["verdict"] == "timelimit"
    assert "external_id" not in submission
    assert data["submissions"][1]["verdict"] is None
    assert data["description"]["contest_key"] == "c"


def test_submission_file_decoding():
    utf8 = SubmissionFileDto(filename="a", content="Grüße\n\nx\n".encode())
    assert utf8.content_safe() == "Grüße\n\nx\n"
    assert utf8.line_count == 2
    assert utf8.byte_size == len("Grüße\n\nx\n".encode())
    legacy = SubmissionFileDto(
        filename="b", content="Größe = 'Straße' # Größenangabe\n".encode("cp1252")
    )
    assert legacy.is_text_file
    # the cached decoding does not take part in equality
    assert utf8 == SubmissionFileDto(filename="a", content="Grüße\n\nx\n".encode())
