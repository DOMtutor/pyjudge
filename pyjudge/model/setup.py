import dataclasses
from typing import Dict, List

from .submission import Verdict


@dataclasses.dataclass
class ScoringSettings(object):
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

