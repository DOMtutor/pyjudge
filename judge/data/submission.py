import dataclasses
from typing import Optional, List

from judge.model import Verdict


@dataclasses.dataclass
class SubmissionFileDto(object):
    filename: str
    content: str


@dataclasses.dataclass
class ParticipantSubmissionDto(object):
    team_key: str
    contest_key: str
    contest_problem_key: str
    language_key: str
    submission_time: float


@dataclasses.dataclass
class SubmissionWithVerdictDto(ParticipantSubmissionDto):
    size: int
    runtime: float
    verdict: Optional[Verdict]
    too_late: bool


@dataclasses.dataclass
class SubmissionWithFilesDto(ParticipantSubmissionDto):
    files: List[SubmissionFileDto]


@dataclasses.dataclass
class ContestProblemDto(object):
    problem_key: str
    contest_problem_key: str
    points: int
    color: Optional[str]


@dataclasses.dataclass
class ClarificationDto(object):
    team_key: str
    contest_key: str
    contest_problem_key: str

    request_time: float
    response: Optional["ClarificationDto"]
    from_jury: bool
    body: str
