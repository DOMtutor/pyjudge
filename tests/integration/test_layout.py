"""The grading layout of pydomjudge-course on an export of judged submissions."""

import datetime
import pathlib
import time
import uuid

import httpx
import pytest

from pydomjudge.database import Database
from pydomjudge.model import Contest, Verdict
from pydomjudge.scripts.export import fetch_contest
from pydomjudge_course.layout import Deadlines, build_layout

from .conftest import ADMIN, JUDGE, TEAM, client

HELLO = pathlib.Path(__file__).parent / "hello"


def _submit_and_wait(team_api: httpx.Client, api: httpx.Client, source: bytes) -> str:
    contest_id = api.get("/api/v4/contests").json()[0]["id"]
    response = team_api.post(
        f"/api/v4/contests/{contest_id}/submissions",
        data={"problem": "helloworld", "language": "python"},
        files={"code[]": ("hello.py", source)},
    )
    assert response.status_code == 200, response.text
    submission_id = response.json()["id"]
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        judgements = api.get(
            f"/api/v4/contests/{contest_id}/judgements",
            params={"submission_id": submission_id},
        ).json()
        if any(j.get("judgement_type_id") for j in judgements if j.get("valid", True)):
            return submission_id
        time.sleep(3)
    pytest.fail(f"submission {submission_id} was not judged")


@pytest.mark.skipif(not JUDGE, reason="needs the judgehost (run.sh with judge)")
def test_layout_of_judged_submissions(
    base_url: str, database: Database, uploaded: Contest, tmp_path: pathlib.Path
):
    marker = uuid.uuid4().hex.encode()
    correct = (HELLO / "hello.py").read_bytes() + b"# " + marker + b"\n"
    wrong = b'print("Goodbye")  # ' + marker + b"\n"
    with client(base_url, auth=TEAM) as team_api, client(base_url, auth=ADMIN) as api:
        _submit_and_wait(team_api, api, correct)
        time.sleep(1.5)  # distinct whole seconds, the end goes between them
        _submit_and_wait(team_api, api, wrong)

    export = fetch_contest(database, uploaded.short_name)
    ours = sorted(
        (
            s
            for s in export.submissions
            if any(marker in file.content for file in s.files)
        ),
        key=lambda s: s.submission_time,
    )
    assert [s.files[0].content for s in ours] == [correct, wrong]
    first, second = (s.submission_time for s in ours)
    end = datetime.datetime.fromtimestamp((first + second) / 2, datetime.UTC)
    team = ours[0].team_name

    evaluation = build_layout(export, tmp_path, deadlines=Deadlines(end))

    records = {
        record.time: record
        for record in evaluation.teams[team].problems["helloworld"].submissions
    }
    on_time, too_late = records[first], records[second]
    assert on_time.timing == "on_time" and too_late.timing == "too_late"
    assert on_time.verdict == Verdict.CORRECT and on_time.solved
    assert on_time.solved_samples and on_time.source
    assert too_late.verdict == Verdict.WRONG_ANSWER and not too_late.solved
    assert not too_late.solved_samples
    # earlier submissions of this team (other tests) are older still
    assert evaluation.counting(team, "helloworld") == on_time
    # both are kept; the counting one is in final/
    assert (tmp_path / on_time.folder / "hello.py").read_bytes() == correct
    assert (tmp_path / too_late.folder / "hello.py").read_bytes() == wrong
    final = tmp_path / "final" / team / "helloworld" / "hello.py"
    assert final.read_bytes() == correct
    assert "user" in evaluation.teams[team].members
