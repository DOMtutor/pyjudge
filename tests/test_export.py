"""Contest exports (database DTOs): JSON format and round trip."""

import json

from pydomjudge.database import (
    ContestDataExport,
    SubmissionFileDto,
)


def test_export_roundtrip(contest_export: ContestDataExport):
    assert (
        ContestDataExport.model_validate_json(contest_export.model_dump_json())
        == contest_export
    )
    assert (
        ContestDataExport.model_validate(contest_export.model_dump()) == contest_export
    )


def test_export_json_format(contest_export: ContestDataExport):
    data = json.loads(contest_export.model_dump_json())
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
