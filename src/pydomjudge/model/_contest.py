from datetime import datetime
from typing import ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)


class ContestProblem(BaseModel):
    name: str
    points: int
    color: str
    problem_key: str


class ContestAccess(BaseModel):
    team_keys: set[str]
    category_keys: set[str]


class Contest(BaseModel):
    DATE_FORMAT: ClassVar[str] = "%Y-%m-%dT%H:%M:%S"

    key: str
    short_name: str
    name: str

    activation_time: datetime
    start_time: datetime
    end_time: datetime
    freeze_time: datetime | None
    deactivation_time: datetime | None

    problems: list[ContestProblem]

    public_scoreboard: bool

    access: ContestAccess | None = None
    warning_message: str = ""

    @field_validator(
        "activation_time",
        "start_time",
        "end_time",
        "freeze_time",
        "deactivation_time",
    )
    @classmethod
    def _require_named_timezone(cls, dt: datetime | None, info: ValidationInfo):
        # Runs before the ordering checks below, which cannot compare naive and
        # aware datetimes. The zone name is needed to write the JSON format.
        if dt is None:
            return dt
        name = info.field_name
        if dt.tzinfo is None:
            raise ValueError(f"{name} has no timezone")
        if not hasattr(dt.tzinfo, "key"):
            raise ValueError(
                f"{name} has a timezone without name -- use "
                "dt.replace(tzinfo=ZoneInfo(...)) to get a proper timezone"
            )
        return dt

    @model_validator(mode="after")
    def validate_contest(self):
        if self.start_time < self.activation_time:
            raise ValueError("Start before activate")
        if self.end_time < self.start_time:
            raise ValueError("End before start")
        if (
            self.deactivation_time is not None
            and self.deactivation_time < self.end_time
        ):
            raise ValueError("Deactivated before end")
        if self.freeze_time is not None and not (
            self.start_time <= self.freeze_time <= self.end_time
        ):
            raise ValueError("Freeze not during contest")
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
            dt, _, tz = v.partition(" ")
            try:
                zone = ZoneInfo(tz)
            except (ZoneInfoNotFoundError, ValueError):
                # KeyError subclass, which pydantic would not report
                raise ValueError(
                    f"Expected '{Contest.DATE_FORMAT} <IANA zone>', got {v!r}"
                ) from None
            return datetime.strptime(dt, Contest.DATE_FORMAT).replace(tzinfo=zone)
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
        end = self.deactivation_time if self.deactivation_time else self.end_time
        return self.activation_time <= point <= end

    def __str__(self):
        return f"C({self.short_name})"
