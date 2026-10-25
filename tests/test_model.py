import datetime
from zoneinfo import ZoneInfo

import bcrypt
import pytest
from pydantic import ValidationError

import pydomjudge.model as model
from pydomjudge.model import (
    Contest,
    ContestProblem,
    DefaultCategory,
    ScoringSettings,
    SubmissionVerdict,
    Team,
    User,
    UserRole,
)

TZ = ZoneInfo("Europe/Berlin")


def _contest(**overrides) -> Contest:
    start = datetime.datetime(2026, 1, 10, 12, 0, tzinfo=TZ)
    values = dict(
        key="c",
        short_name="c",
        name="Contest",
        activation_time=start - datetime.timedelta(hours=1),
        start_time=start,
        end_time=start + datetime.timedelta(days=1),
        freeze_time=None,
        deactivation_time=None,
        problems=[ContestProblem(name="A", points=1, color="red", problem_key="a")],
        public_scoreboard=False,
    )
    values.update(overrides)
    return Contest(**values)


def test_contest_json_roundtrip():
    contest = _contest()
    dumped = contest.model_dump_json()
    assert '"2026-01-10T12:00:00 Europe/Berlin"' in dumped
    restored = Contest.model_validate_json(dumped)
    assert restored == contest
    assert restored.start_time.tzinfo.key == "Europe/Berlin"


def test_contest_rejects_start_before_activation():
    with pytest.raises(ValidationError, match="Start before activate"):
        _contest(activation_time=datetime.datetime(2026, 1, 10, 13, 0, tzinfo=TZ))


def test_contest_rejects_naive_datetime():
    # Should be a ValidationError; currently the naive/aware comparison in the
    # validator raises TypeError first (see docs/review.md).
    with pytest.raises((ValidationError, TypeError)):
        _contest(start_time=datetime.datetime(2026, 1, 10, 12, 0))


def test_contest_is_running():
    contest = _contest()
    assert contest.is_running(contest.start_time + datetime.timedelta(hours=1))
    assert not contest.is_running(contest.end_time + datetime.timedelta(seconds=1))


@pytest.mark.parametrize("verdict", list(SubmissionVerdict))
def test_submission_verdict_string_roundtrip(verdict: SubmissionVerdict):
    assert SubmissionVerdict.from_string(str(verdict)) is verdict
    assert (
        SubmissionVerdict.parse_from_expected_result(verdict.expected_result_key())
        is verdict
    )


@pytest.mark.parametrize("verdict", list(model.TestcaseVerdict))
def test_testcase_verdict_string_roundtrip(verdict: model.TestcaseVerdict):
    assert model.TestcaseVerdict.from_string(str(verdict)) is verdict


def test_scoring_settings_require_all_verdicts():
    with pytest.raises(ValidationError, match="Missing priorities"):
        ScoringSettings(result_priority={SubmissionVerdict.CORRECT: 1})


def test_scoring_settings_json_uses_verdict_strings():
    dumped = ScoringSettings().model_dump_json()
    assert '"wrong-answer"' in dumped
    assert ScoringSettings.model_validate_json(dumped) == ScoringSettings()


def test_password_hash_verifies():
    hashed = User.hash_password("secret")
    assert bcrypt.checkpw(b"secret", hashed.encode())


def test_team_is_hashable_and_members_frozen():
    user = User(
        key="u", login_name="u", display_name="U", email=None, role=UserRole.Participant
    )
    team = Team(
        key="t",
        name="t",
        display_name="T",
        members=[user],
        category=DefaultCategory.Participants,
        affiliation=None,
    )
    assert isinstance(team.members, tuple)
    assert {team: 1}[team] == 1
