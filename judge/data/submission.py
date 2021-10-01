import dataclasses
from typing import Optional

from judge.model import Team, ContestProblem, Language, Verdict, Problem, Contest


@dataclasses.dataclass
class ParticipantSubmission(object):
    team: Team
    problem: ContestProblem
    language: Language
    size: int

    verdict: Optional[Verdict]
    submission_time: float


@dataclasses.dataclass
class Clarification(object):
    team: Team
    request_time: float
    answer: Optional["Clarification"]

    problem: Optional[Problem]
    contest: Contest
