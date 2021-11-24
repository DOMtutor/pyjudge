import dataclasses
from datetime import datetime
from typing import Optional, List, Set

import dateutil.parser

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
        return ContestProblem(name=data["name"], points=data["points"], color=data["color"],
                              problem=problem_loader.load_problem(data["problem"]))

    def serialize(self, problem_loader: ProblemLoader):
        return {"name": self.name, "points": self.points, "color": self.color,
                "problem": problem_loader.serialize_problem(self.problem)}

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
        team_categories = set(TeamCategory.parse(name) for name in data.get("categories", []))
        return ContestAccess(team_names=team_names, team_categories=team_categories)

    def serialize(self):
        return {
            "teams": list(self.team_names),
            "categories": [category.configuration_key for category in self.team_categories]
        }


@dataclasses.dataclass
class Contest(object):
    DATE_FORMAT = "%Y-%m-%dT%H:%M:%S %Z"

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
        if self.start_time < self.activation_time:
            raise ValueError("Start before activate")
        if self.end_time < self.start_time:
            raise ValueError("End before start")
        if self.deactivation_time is not None:
            if self.deactivation_time < self.end_time:
                raise ValueError("Deactivated before end")
        if self.freeze_time is not None:
            if self.freeze_time < self.start_time or self.end_time < self.freeze_time:
                raise ValueError("Freeze not during contest")

    def is_running(self, at: datetime):
        return self.start_time <= at <= self.end_time

    @staticmethod
    def parse(data, problem_loader: ProblemLoader):
        public_scoreboard = data.get("public_scoreboard", False)
        problems = [ContestProblem.parse(problem, problem_loader) for problem in data["problems"]]

        activate = dateutil.parser.parse(data["activate"])
        start = dateutil.parser.parse(data["start"])
        end = dateutil.parser.parse(data["end"])
        freeze = data.get("freeze", None)
        if freeze is not None:
            freeze = dateutil.parser.parse(freeze)
        deactivation = data.get("deactivate", None)
        if deactivation is not None:
            deactivation = dateutil.parser.parse(deactivation)
        access = ContestAccess.parse(data["access"]) if data.get("access", None) is not None else None

        return Contest(key=data["key"], name=data["name"],
                       activation_time=activate, start_time=start, end_time=end, freeze_time=freeze,
                       deactivation_time=deactivation, access=access, public_scoreboard=public_scoreboard,
                       problems=problems)

    def serialize(self, problem_loader: ProblemLoader):
        self.validate()
        data = {
            "key": self.key,
            "name": self.name,
            "activate": self.activation_time.strftime(Contest.DATE_FORMAT),
            "start": self.start_time.strftime(Contest.DATE_FORMAT),
            "end": self.end_time.strftime(Contest.DATE_FORMAT),
            "problems": [problem.serialize(problem_loader) for problem in self.problems]
        }
        if self.access is not None:
            data["access"] = self.access.serialize()
        if self.freeze_time is not None:
            data["freeze"] = self.freeze_time.strftime(Contest.DATE_FORMAT)
        if self.deactivation_time is not None:
            data["deactivate"] = self.deactivation_time.strftime(Contest.DATE_FORMAT)
        return data

    def is_active(self, point: datetime):
        return self.activation_time <= point <= self.end_time

    def __str__(self):
        return f"C({self.key})"