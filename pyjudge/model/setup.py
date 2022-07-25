import dataclasses
from typing import Dict, List, Set

from .submission import Verdict


@dataclasses.dataclass
class ScoringSettings(object):
    @staticmethod
    def parse_verdict(key):
        return {
            "correct": Verdict.CORRECT,
            "wrong_answer": Verdict.WRONG_ANSWER,
            "time_limit": Verdict.TIME_LIMIT,
            "run_error": Verdict.RUN_ERROR,
            "memory_limit": Verdict.MEMORY_LIMIT,
            "output_limit": Verdict.OUTPUT_LIMIT,
            "no_output": Verdict.NO_OUTPUT
        }[key]

    @staticmethod
    def parse_scoring(data) -> "ScoringSettings":
        priorities: Dict[Verdict, int] = dict()
        for key, priority in data["results_priority"].items():
            priorities[ScoringSettings.parse_verdict(key)] = priority
        return ScoringSettings(penalty_time=data["penalty_time"], result_priority=priorities)

    penalty_time: float
    result_priority: Dict[Verdict, int]


@dataclasses.dataclass
class JudgingSettings(object):
    memory_limit: int
    output_limit: int
    source_size_limit: int
    source_file_limit: int
    script_time_limit: int
    script_memory_limit: int
    script_size_limit: int
    time_overshoot: str
    output_storage_limit: int
    output_display_limit: int
    lazy_eval: bool


@dataclasses.dataclass
class DisplaySettings(object):
    show_pending: bool
    show_flags: bool
    show_affiliations: bool
    show_affiliation_logos: bool
    show_teams_submissions: bool
    show_sample_output: bool
    show_compile: int


@dataclasses.dataclass
class ClarificationSettings(object):
    answers: List[str]


@dataclasses.dataclass
class JudgeSettings(object):
    judging: JudgingSettings
    scoring: ScoringSettings
    display: DisplaySettings
    clarification: ClarificationSettings

    @staticmethod
    def parse_settings(data):
        scoring = ScoringSettings.parse_scoring(data["score"])
        judging = JudgingSettings(**data["judging"])
        display = DisplaySettings(**data["display"])
        clarification = ClarificationSettings(**data["clarification"])
        return JudgeSettings(judging=judging, scoring=scoring, display=display, clarification=clarification)
