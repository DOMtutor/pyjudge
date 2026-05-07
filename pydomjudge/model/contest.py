from datetime import datetime
from typing import ClassVar

import pytz
from pydantic import (
    BaseModel,
    model_validator,
    field_serializer,
    field_validator,
)


class ContestProblem(BaseModel):
    name: str
    points: int
    color: str
    problem_key: str

    def __hash__(self):
        return hash(self.problem_key)

    def __eq__(self, other):
        return (
            isinstance(other, ContestProblem) and self.problem_key == other.problem_key
        )


class ContestAccess(BaseModel):
    team_keys: set[str]
    team_category_keys: set[str]


class Contest(BaseModel):
    DATE_FORMAT: ClassVar[str] = "%Y-%m-%dT%H:%M:%S"

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
        return self

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
    def _parse_datetime(cls, v: str | datetime):
        if isinstance(v, str):
            dt, tz = v.split(" ")
            return pytz.timezone(tz).localize(
                datetime.strptime(dt, Contest.DATE_FORMAT)
            )
        return v

    @field_serializer(
        "activation_time",
        "start_time",
        "end_time",
        "freeze_time",
        "deactivation_time",
        when_used="json",
    )
    def _serialize_datetime(self, dt: datetime | None):
        if dt is None:
            return None
        assert dt.tzinfo is not None and hasattr(dt.tzinfo, "key")
        # noinspection PyUnresolvedReferences
        return f"{dt.strftime(Contest.DATE_FORMAT)} {dt.tzinfo.key}"

    def is_active(self, point: datetime):
        return self.activation_time <= point <= self.end_time

    def __str__(self):
        return f"C({self.key})"
