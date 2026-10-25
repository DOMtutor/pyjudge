from pydomjudge.model import (
    ClarificationSettings,
    DefaultCategory,
    DisplaySettings,
    JudgeInstance,
    JudgeSettings,
    JudgingSettings,
    ScoringSettings,
)


def make_settings():
    judge_settings = JudgeSettings(
        judging=JudgingSettings(),
        scoring=ScoringSettings(),
        display=DisplaySettings(),
        clarification=ClarificationSettings(),
    )
    return JudgeInstance(
        identifier="local",
        settings=judge_settings,
        base_time=1.5,
        user_whitelist=set(),
        allowed_language_keys=None,
        team_categories=[DefaultCategory.Participants],
    )
