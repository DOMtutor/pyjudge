from datetime import datetime
from typing import Any, ClassVar

import pytz
from pydantic import (
    BaseModel,
    model_validator,
    field_serializer,
    field_validator,
    ConfigDict,
)
from pydantic_core.core_schema import ValidationInfo, FieldSerializationInfo

from .problem import Problem, ProblemLoader


class ContestProblem(BaseModel):
    name: str
    points: int
    color: str
    problem: Problem

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator("problem", mode="before")
    @classmethod
    def _parse_problem_key(cls, v, info: ValidationInfo):
        if not info.context:
            raise ValueError("No context provided")
        loader = info.context.get("problem_loader")
        return loader.load_problem(v)

    @field_serializer("problem", when_used="json")
    def _serialize_problem(self, problem: Any, info: FieldSerializationInfo) -> Any:
        if not info.context:
            raise ValueError("No context provided")
        loader = info.context.get("problem_loader")
        return loader.serialize_problem(problem)

    def __hash__(self):
        return hash(self.problem)

    def __eq__(self, other):
        return isinstance(other, ContestProblem) and self.problem == other.problem


class ContestAccess(BaseModel):
    team_names: set[str]
    team_categories: set[str]


class Contest(BaseModel):
    DATE_FORMAT: ClassVar[str] = "%Y-%m-%dT%H:%M:%S"

    @staticmethod
    def load(data: str | bytes, loader: ProblemLoader):
        return Contest.model_validate_json(data, context={"problem_loader": loader})

    key: str
    name: str

    activation_time: datetime
    start_time: datetime
    end_time: datetime
    freeze_time: datetime | None
    deactivation_time: datetime | None

    problems: list[ContestProblem]
    access: ContestAccess | None

    public_scoreboard: bool

    @model_validator(mode="after")
    def validate_contest(self):
        if self.activation_time.tzinfo is None:
            raise ValueError("Activation has no timezone")
        if self.start_time < self.activation_time:
            raise ValueError("Start before activate")
        if self.start_time.tzinfo is None:
            raise ValueError("Start has no timezone")
        if self.end_time < self.start_time:
            raise ValueError("End before start")
        if self.end_time.tzinfo is None:
            raise ValueError("End has no timezone")
        if self.deactivation_time is not None:
            if self.deactivation_time < self.end_time:
                raise ValueError("Deactivated before end")
            if self.deactivation_time.tzinfo is None:
                raise ValueError("Deactivation has no timezone")
        if self.freeze_time is not None:
            if self.freeze_time < self.start_time or self.end_time < self.freeze_time:
                raise ValueError("Freeze not during contest")
            if self.freeze_time.tzinfo is None:
                raise ValueError("Start has no timezone")

    def is_running(self, at: datetime):
        return self.start_time <= at <= self.end_time

    @field_validator(
        "activation_time",
        "start_time",
        "end_time",
        "freeze_time",
        "deactivation_time",
        mode="before",
    )
    @classmethod
    def _parse_datetime(cls, v: str):
        dt, tz = v.split(" ")
        return pytz.timezone(tz).localize(datetime.strptime(dt, Contest.DATE_FORMAT))

    @field_serializer(
        "activation_time",
        "start_time",
        "end_time",
        "freeze_time",
        "deactivation_time",
        when_used="json",
    )
    def _serialize_datetime(self, dt: datetime):
        assert dt.tzinfo is not None
        return f"{dt.strftime(Contest.DATE_FORMAT)} {dt.tzinfo.tzname(dt)}"

    def is_active(self, point: datetime):
        return self.activation_time <= point <= self.end_time

    def __str__(self):
        return f"C({self.key})"
