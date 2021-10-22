import dataclasses
from datetime import datetime
from typing import Optional, List

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
class Contest(object):
    DATE_FORMAT = "%Y-%m-%dT%H:%M:%S %Z"

    key: str
    name: str

    activation_time: datetime
    start_time: datetime
    end_time: datetime
    freeze_time: Optional[datetime]

    problems: List[ContestProblem]

    allowed_team_names: List[str]
    allowed_team_categories: List[TeamCategory]
    public: bool

    def is_running(self, at: datetime):
        return self.start_time <= at <= self.end_time

    @staticmethod
    def parse(data, problem_loader: ProblemLoader):
        public = data.get("is_public", False)
        if public:
            allowed_team_names = []
            allowed_team_categories = []
        else:
            allowed_team_names = [data.get("allowed_team_names", [])]
            allowed_team_categories = [TeamCategory.parse(name) for name in data.get("allowed_categories", [])]
        problems = [ContestProblem.parse(problem, problem_loader) for problem in data["problems"]]

        activate = dateutil.parser.parse(data["activate"])
        start = dateutil.parser.parse(data["start"])
        end = dateutil.parser.parse(data["end"])
        freeze = data.get("freeze", None)
        if freeze is not None:
            freeze = dateutil.parser.parse(freeze)

        return Contest(key=data["key"], name=data["name"],
                       activation_time=activate, start_time=start, end_time=end, freeze_time=freeze,
                       allowed_team_names=allowed_team_names,
                       allowed_team_categories=allowed_team_categories,
                       public=public, problems=problems)

    def serialize(self, problem_loader: ProblemLoader):
        return {
            "key": self.key,
            "name": self.name,
            "activate": self.activation_time.strftime(Contest.DATE_FORMAT),
            "start": self.start_time.strftime(Contest.DATE_FORMAT),
            "end": self.end_time.strftime(Contest.DATE_FORMAT),
            "freeze": self.freeze_time.strftime(Contest.DATE_FORMAT) if self.freeze_time else None,
            "problems": [problem.serialize(problem_loader) for problem in self.problems],
            "public": self.public,
            "allowed_team_names": self.allowed_team_names,
            "allowed_categories": [category.configuration_key for category in self.allowed_team_categories]
        }

    def is_active(self, point: datetime):
        return self.activation_time <= point <= self.end_time
