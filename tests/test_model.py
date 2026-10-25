import datetime
import json
from zoneinfo import ZoneInfo

import bcrypt
import pytest
from pydantic import ValidationError

from pydomjudge.model import (
    Contest,
    ContestProblem,
    DefaultCategory,
    JudgeSettings,
    ScoringSettings,
    Team,
    User,
    UserRole,
    Verdict,
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


@pytest.mark.parametrize(
    "field", ["activation_time", "start_time", "end_time", "deactivation_time"]
)
def test_contest_rejects_naive_datetime(field: str):
    with pytest.raises(ValidationError, match=f"{field} has no timezone"):
        _contest(**{field: datetime.datetime(2026, 1, 10, 12, 0)})


def test_contest_rejects_timezone_without_name():
    offset = datetime.timezone(datetime.timedelta(hours=1))
    with pytest.raises(ValidationError, match="freeze_time has a timezone without"):
        _contest(freeze_time=datetime.datetime(2026, 1, 10, 13, 0, tzinfo=offset))


def test_contest_rejects_unknown_zone_name():
    data = json.loads(_contest().model_dump_json())
    data["start_time"] = "2026-01-10T12:00:00 Mars/Olympus"
    with pytest.raises(ValidationError, match="IANA zone"):
        Contest.model_validate(data)


def test_contest_freeze_must_be_during_contest():
    with pytest.raises(ValidationError, match="Freeze not during contest"):
        _contest(freeze_time=datetime.datetime(2026, 1, 9, 12, 0, tzinfo=TZ))


def test_contest_is_active_until_deactivation():
    deactivation = datetime.datetime(2026, 1, 20, 12, 0, tzinfo=TZ)
    contest = _contest(deactivation_time=deactivation)
    assert contest.is_active(contest.end_time + datetime.timedelta(days=1))
    assert not contest.is_active(deactivation + datetime.timedelta(days=1))
    assert not _contest().is_active(contest.end_time + datetime.timedelta(days=1))


def test_contest_is_running():
    contest = _contest()
    assert contest.is_running(contest.start_time + datetime.timedelta(hours=1))
    assert not contest.is_running(contest.end_time + datetime.timedelta(seconds=1))


@pytest.mark.parametrize("verdict", list(Verdict))
def test_verdict_string_roundtrip(verdict: Verdict):
    assert Verdict.parse(verdict.value) is verdict
    assert Verdict.parse(verdict.expected_result_key()) is verdict
    assert verdict.expected_result_key() == verdict.value.upper()


def test_verdict_uses_domjudge_spelling():
    # etc/judgehost-static.php.in and SubmissionService::PROBLEM_RESULT_REMAP
    assert Verdict.TIME_LIMIT == "timelimit"
    assert Verdict.RUN_ERROR.expected_result_key() == "RUN-ERROR"
    assert Verdict.COMPILER_ERROR.expected_result_key() == "COMPILER-ERROR"


@pytest.mark.parametrize(
    ("text", "verdict"),
    [
        # expected_results upper-case DOMjudge's result strings
        ("TIMELIMIT", Verdict.TIME_LIMIT),
        ("RUN-ERROR", Verdict.RUN_ERROR),
        ("WRONG-ANSWER", Verdict.WRONG_ANSWER),
        (" Correct ", Verdict.CORRECT),
    ],
)
def test_verdict_parses_domjudge_strings_case_insensitively(
    text: str, verdict: Verdict
):
    assert Verdict.parse(text) is verdict


@pytest.mark.parametrize("text", ["presentation-error", "AC", ""])
def test_verdict_rejects_unknown(text: str):
    with pytest.raises(ValueError, match="Unknown verdict"):
        Verdict.parse(text)


def test_scoring_settings_require_all_verdicts():
    with pytest.raises(ValidationError, match="Missing priorities"):
        ScoringSettings(result_priority={Verdict.CORRECT: 1})


def test_scoring_settings_json_uses_verdict_strings():
    dumped = ScoringSettings().model_dump_json()
    assert set(json.loads(dumped)["result_priority"]) == {v.value for v in Verdict}
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


def test_judge_settings_defaults_are_independent():
    first, second = JudgeSettings(), JudgeSettings()
    assert first.scoring is not second.scoring
    first.clarification.answers.append("Yes")
    assert "Yes" not in second.clarification.answers


def test_language_is_hashable():
    from pydomjudge.model import Executable, ExecutableType, Language

    script = Executable(
        key="compile_x",
        description="compile X",
        executable_type=ExecutableType.Compile,
        contents=(),
    )
    language = Language(
        key="x",
        name="X",
        time_factor=1.0,
        extensions=frozenset({"x"}),
        entry_point_description=None,
        entry_point_required=False,
        compile_script=script,
    )
    assert {language: 1}[language] == 1
