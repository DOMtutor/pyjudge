import dataclasses
from typing import Dict

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
class JudgeSettings(object):
    judging: JudgingSettings
    scoring: ScoringSettings
