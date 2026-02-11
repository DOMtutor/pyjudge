import dataclasses
from datetime import datetime
from typing import Optional, List, Set, Any

import pytz

from .problem import Problem, ProblemLoader
from .team import TeamCategory


@dataclasses.dataclass
class ContestProblem(object):
    name: str
    points: int
    color: str
    problem: Problem

    @staticmethod
    def parse(data, problem_loader: ProblemLoader):
        return ContestProblem(
            name=data["name"],
            points=data["points"],
            color=data["color"],
            problem=problem_loader.load_problem(data["problem"]),
        )

    def serialize(self, problem_loader: ProblemLoader):
        return {
            "name": self.name,
            "points": self.points,
            "color": self.color,
            "problem": problem_loader.serialize_problem(self.problem),
        }

    def __hash__(self):
        return hash(self.problem)

    def __eq__(self, other):
        return isinstance(other, ContestProblem) and self.problem == other.problem


@dataclasses.dataclass
class ContestAccess(object):
    team_names: Set[str]
    team_categories: Set[TeamCategory]

    @staticmethod
    def parse(data):
        team_names = set(data.get("teams", []))
        team_categories = set(
            TeamCategory.parse(key, data)
            for key, data in data.get("categories", {}).items()
        )
        return ContestAccess(team_names=team_names, team_categories=team_categories)

    def serialize(self):
        return {
            "teams": list(self.team_names),
            "categories": {
                category.json_ref(): category.serialize()
                for category in self.team_categories
            },
        }


@dataclasses.dataclass
class Contest(object):
    DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

    key: str
    name: str

    activation_time: datetime
    start_time: datetime
    end_time: datetime
    freeze_time: Optional[datetime]
    deactivation_time: Optional[datetime]

    problems: List[ContestProblem]
    access: Optional[ContestAccess]

    public_scoreboard: bool

    def __post_init__(self):
        self.validate()

    def validate(self):
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

    @staticmethod
    def _format_datetime(dt: datetime):
        assert dt.tzinfo is not None
        return f"{dt.strftime(Contest.DATE_FORMAT)} {dt.tzinfo.tzname(dt)}"

    @staticmethod
    def _parse_datetime(string: str):
        dt, tz = string.split(" ")
        return pytz.timezone(tz).localize(datetime.strptime(dt, Contest.DATE_FORMAT))

    @staticmethod
    def parse(data, problem_loader: ProblemLoader):
        public_scoreboard = data.get("public_scoreboard", False)
        problems = [
            ContestProblem.parse(problem, problem_loader)
            for problem in data["problems"]
        ]

        activate = Contest._parse_datetime(data["activate"])
        start = Contest._parse_datetime(data["start"])
        end = Contest._parse_datetime(data["end"])
        freeze = data.get("freeze", None)
        if freeze is not None:
            freeze = Contest._parse_datetime(freeze)
        deactivation = data.get("deactivate", None)
        if deactivation is not None:
            deactivation = Contest._parse_datetime(deactivation)
        access = (
            ContestAccess.parse(data["access"])
            if data.get("access", None) is not None
            else None
        )

        return Contest(
            key=data["key"],
            name=data["name"],
            activation_time=activate,
            start_time=start,
            end_time=end,
            freeze_time=freeze,
            deactivation_time=deactivation,
            access=access,
            public_scoreboard=public_scoreboard,
            problems=problems,
        )

    def serialize(self, problem_loader: ProblemLoader):
        self.validate()
        data: dict[str, Any] = {
            "key": self.key,
            "name": self.name,
            "activate": Contest._format_datetime(self.activation_time),
            "start": Contest._format_datetime(self.start_time),
            "end": Contest._format_datetime(self.end_time),
            "problems": [
                problem.serialize(problem_loader) for problem in self.problems
            ],
        }
        if self.access is not None:
            data["access"] = self.access.serialize()
        if self.freeze_time is not None:
            data["freeze"] = Contest._format_datetime(self.freeze_time)
        if self.deactivation_time is not None:
            data["deactivate"] = Contest._format_datetime(self.deactivation_time)
        return data

    def is_active(self, point: datetime):
        return self.activation_time <= point <= self.end_time

    def __str__(self):
        return f"C({self.key})"
