from pydantic import BaseModel, Field, model_validator
from typing import Sequence

from .team import TeamCategory
from .submission import Verdict, PydanticVerdict


class ScoringSettings(BaseModel):
    penalty_time: float = 600.0
    result_priority: dict[PydanticVerdict, int] = Field(
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

    @model_validator(mode="after")
    def _validate_all_verdicts_present(self):
        missing = set(Verdict) - set(self.result_priority.keys())
        if missing:
            missing_str = ", ".join(v.name for v in missing)
            raise ValueError(f"Missing priorities for verdicts: {missing_str}")
        return self


class JudgingSettings(BaseModel):
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


class DisplaySettings(BaseModel):
    show_pending: bool = True
    show_flags: bool = False
    show_affiliations: bool = True
    show_affiliation_logos: bool = False
    show_teams_submissions: bool = True
    show_sample_output: bool = True
    show_compile: int = 1


class ClarificationSettings(BaseModel):
    answers: Sequence[str] = ("No comment", "Read the problem statement carefully")


class JudgeSettings(BaseModel):
    judging: JudgingSettings
    scoring: ScoringSettings
    display: DisplaySettings
    clarification: ClarificationSettings


class JudgeInstance(BaseModel):
    identifier: str = Field(serialization_alias="id")
    settings: JudgeSettings
    base_time: float
    user_whitelist: set[str]
    allowed_language_keys: set[str] | None
    team_categories: list[TeamCategory]
