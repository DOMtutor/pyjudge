import dataclasses
from dataclasses import field
from typing import Sequence

from .team import TeamCategory
from .submission import Verdict
from pydomjudge.util import list_if_not_none, filter_none


@dataclasses.dataclass
class ScoringSettings(object):
    penalty_time: float = 600.0
    result_priority: dict[Verdict, int] = field(
        default_factory=lambda: {
            Verdict.TIME_LIMIT: 70,
            Verdict.MEMORY_LIMIT: 95,
            Verdict.OUTPUT_LIMIT: 90,
            Verdict.RUN_ERROR: 85,
            Verdict.WRONG_ANSWER: 80,
            Verdict.NO_OUTPUT: 99,
            Verdict.PRESENTATION_ERROR: 98,
            Verdict.COMPILER_ERROR: 100,
            Verdict.CORRECT: 1,
        }
    )

    def __post_init__(self):
        if not self.result_priority.keys() == set(Verdict):
            missing_verdicts = (
                str(verdict)
                for verdict in Verdict
                if verdict not in self.result_priority
            )
            raise ValueError(
                f"Missing priorities for verdicts {','.join(missing_verdicts)}"
            )

    @staticmethod
    def parse_scoring(data) -> "ScoringSettings":
        if "result_priority" in data:
            data["result_priority"] = {
                Verdict.parse(key): priority
                for key, priority in data["result_priority"].items()
            }
        return ScoringSettings(**data)

    def serialize(self):
        return {
            "penalty_time": self.penalty_time,
            "result_priority": {
                key.serialize(): value for key, value in self.result_priority.items()
            },
        }


@dataclasses.dataclass
class JudgingSettings(object):
    memory_limit: int = 1572864
    output_limit: int = 8192
    source_size_limit: int = 256
    source_file_limit: int = 1
    script_time_limit: int = 30
    script_memory_limit: int = 2097152
    script_size_limit: int = 2621440
    time_overshoot: str = "2s+50%"
    output_storage_limit: int = 50000
    output_display_limit: int = 2000
    lazy_eval: bool = False

    @staticmethod
    def parse_judging(data):
        return JudgingSettings(**data)

    def serialize(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass
class DisplaySettings(object):
    show_pending: bool = True
    show_flags: bool = False
    show_affiliations: bool = True
    show_affiliation_logos: bool = False
    show_teams_submissions: bool = True
    show_sample_output: bool = True
    show_compile: int = 1

    @staticmethod
    def parse_display(data):
        return DisplaySettings(**data)

    def serialize(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass
class ClarificationSettings(object):
    answers: Sequence[str] = ("No comment", "Read the problem statement carefully")

    @staticmethod
    def parse_clarification(data):
        return ClarificationSettings(**data)

    def serialize(self):
        return dataclasses.asdict(self)


@dataclasses.dataclass
class JudgeSettings(object):
    judging: JudgingSettings
    scoring: ScoringSettings
    display: DisplaySettings
    clarification: ClarificationSettings

    @staticmethod
    def parse_settings(data):
        scoring = ScoringSettings.parse_scoring(data.get("score", {}))
        judging = JudgingSettings.parse_judging(data.get("judging", {}))
        display = DisplaySettings.parse_display(data.get("display", {}))
        clarification = ClarificationSettings.parse_clarification(
            data.get("clarification", {})
        )
        return JudgeSettings(
            judging=judging,
            scoring=scoring,
            display=display,
            clarification=clarification,
        )

    def serialize(self):
        return {
            "score": self.scoring.serialize(),
            "judging": self.judging.serialize(),
            "display": self.display.serialize(),
            "clarification": self.clarification.serialize(),
        }


@dataclasses.dataclass
class JudgeInstance(object):
    identifier: str
    settings: JudgeSettings
    base_time: float
    user_whitelist: set[str]
    allowed_language_keys: set[str] | None
    team_categories: list[TeamCategory]

    @staticmethod
    def parse_instance(data):
        return JudgeInstance(
            identifier=data["id"],
            settings=JudgeSettings.parse_settings(data["settings"]),
            base_time=data["base_time"],
            user_whitelist=set(data["user_whitelist"]),
            allowed_language_keys=set(data["language_keys"])
            if "language_keys" in data
            else None,
            team_categories=list(
                TeamCategory.parse(key, value)
                for key, value in data.get("team_categories", {}).items()
            ),
        )

    def serialize(self):
        return filter_none(
            {
                "id": self.identifier,
                "settings": self.settings.serialize(),
                "base_time": self.base_time,
                "user_whitelist": list(self.user_whitelist),
                "language_keys": list_if_not_none(self.allowed_language_keys),
                "team_categories": {
                    category.json_ref: category.serialize()
                    for category in self.team_categories
                },
            }
        )
